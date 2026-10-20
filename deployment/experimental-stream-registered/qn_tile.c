// SPDX-License-Identifier: GPL-2.0
/* AXI DMAengine client for QNT1 tiles and QNC2 cached layers. */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/compat.h>
#include <linux/dmaengine.h>
#include <linux/dma-mapping.h>
#include <linux/completion.h>
#include <linux/gpio/consumer.h>
#include <linux/delay.h>
#include <linux/kref.h>
#include <linux/mutex.h>
#include <linux/slab.h>
#include <asm/unaligned.h>
#include "qn_tile_uapi.h"
#include "qn_cache_protocol.h"
#include "qn_stream_registered.h"

struct qn_stream_program {
    struct file *owner;
    void *data;
    dma_addr_t dma;
    u64 handle;
    u32 bytes, capacity, stages, tag, header_bytes, tail_offset;
};

struct qn_completion {
	struct completion *done;
	bool failed;
};

struct qn_tile {
	struct device *dev;
	struct miscdevice misc;
	struct kref refs;
	struct mutex lock;
	struct dma_chan *tx, *rx;
	struct gpio_desc *reset, *error;
	struct completion tx_done, rx_done;
	struct qn_completion tx_result[QN_TILE_MAX_BATCH];
	struct qn_completion rx_result[QN_TILE_MAX_BATCH];
	void *input, *output;
	dma_addr_t input_dma, output_dma;
	bool removed, poisoned, cache_quant, needs_rebind, dw_valid;
	struct file *slot_owner[32];u32 slot_tag[32];bool slot_dw_valid[32];
	struct file *cache_owner;
	u32 cache_tag, cache_k, cache_m;
    struct qn_stream_program programs[QN_STREAM_PROGRAMS];
    u64 next_program;
    u32 program_memory;
};

static void qn_free(struct kref *refs)
{
	struct qn_tile *q = container_of(refs, struct qn_tile, refs);
	put_device(q->dev);
	kfree(q);
}

static void qn_callback(void *arg, const struct dmaengine_result *result)
{
	struct qn_completion *cb = arg;
	/* Persistent callback storage also survives failed termination. */
	cb->failed = !result || result->result != DMA_TRANS_NOERROR || result->residue;
	if (cb->done)
		complete(cb->done);
}

static void qn_reset(struct qn_tile *q)
{
	memset(q->slot_owner,0,sizeof(q->slot_owner));
	memset(q->slot_dw_valid,0,sizeof(q->slot_dw_valid));
	q->cache_owner = NULL;
	q->dw_valid = false;
	/* DT GPIO_ACTIVE_LOW: logical 1 drives the physical reset low. */
	gpiod_set_value_cansleep(q->reset, 1);
	usleep_range(1000, 2000);
	gpiod_set_value_cansleep(q->reset, 0);
	usleep_range(1000, 2000);
}

static int qn_stop(struct qn_tile *q)
{
	int tx = dmaengine_terminate_sync(q->tx);
	int rx = dmaengine_terminate_sync(q->rx);
	qn_reset(q);
	if (tx || rx) {
		/* Do not free DMA memory or callback storage after failed termination.
		 * Quarantine this instance and pin its module until reboot. */
		if (!q->poisoned) {
			q->poisoned = true;
			__module_get(THIS_MODULE);
		}
		dev_err(q->dev, "DMA termination failed (%d/%d); instance quarantined\n", tx, rx);
		return -EIO;
	}
	return 0;
}

static int qn_open(struct inode *inode, struct file *file)
{
	struct qn_tile *q = container_of(file->private_data, struct qn_tile, misc);
	int ret = 0;
	mutex_lock(&q->lock);
	if (q->removed)
		ret = -ENODEV;
	else {
		kref_get(&q->refs);
		file->private_data = q;
	}
	mutex_unlock(&q->lock);
	return ret;
}

/* Called with the device lock held and only after DMA has stopped safely.
 * Header and activation cache lines belong to CPU; the immutable middle
 * remains device-owned between runs. Return the whole mapping before free. */
static void qn_program_free(struct qn_tile *q, struct qn_stream_program *p)
{
    if (!p->data || q->poisoned) return;
    dma_sync_single_for_cpu(q->tx->device->dev,p->dma,p->capacity,DMA_TO_DEVICE);
    dma_free_noncoherent(q->tx->device->dev,p->capacity,p->data,p->dma,DMA_TO_DEVICE);
    q->program_memory-=p->capacity;
    memset(p,0,sizeof(*p));
}

static struct qn_stream_program *qn_program_find(struct qn_tile *q, struct file *file, u64 handle)
{
    unsigned i;
    for(i=0;i<QN_STREAM_PROGRAMS;i++)
        if(q->programs[i].data && q->programs[i].owner==file && q->programs[i].handle==handle)
            return &q->programs[i];
    return NULL;
}

static long qn_program_ioctl(struct file *file,unsigned cmd,unsigned long arg)
{
    struct qn_tile *q=file->private_data;
    struct qn_stream_register r;
    struct qn_stream_program *p=NULL;
    struct qn_layer_command command;
    u64 handle;
    u32 n,alignment;
    unsigned i;
    int ret;
    if(cmd==QN_STREAM_RELEASE){
        if(copy_from_user(&handle,(void __user *)arg,sizeof(handle)))return -EFAULT;
        if(!handle)return -EINVAL;
    }else{
        if(copy_from_user(&r,(void __user *)arg,sizeof(r)))return -EFAULT;
        if(r.handle || r.flags || r.reserved || r.prefix_bytes<qn_stream_prefix_bytes(1) ||
           r.prefix_bytes>qn_stream_prefix_bytes(8))return -EINVAL;
    }
    ret=mutex_lock_interruptible(&q->lock);if(ret)return ret;
    if(q->removed || q->poisoned || q->needs_rebind){ret=q->removed?-ENODEV:-EIO;goto done;}
    if(cmd==QN_STREAM_RELEASE){
        p=qn_program_find(q,file,handle);
        if(!p){ret=-ESTALE;goto done;}
        qn_program_free(q,p);ret=0;goto done;
    }
    for(i=0;i<QN_STREAM_PROGRAMS;i++)if(!q->programs[i].data){p=&q->programs[i];break;}
    if(!p || q->next_program==U64_MAX){ret=-ENOSPC;goto done;}
    alignment=dma_get_cache_alignment();
    if(!alignment || !is_power_of_2(alignment)){ret=-EOPNOTSUPP;goto done;}
    p->capacity=ALIGN(r.prefix_bytes+65536,alignment);
    if(p->capacity>QN_STREAM_MEMORY_LIMIT-q->program_memory){p->capacity=0;ret=-ENOSPC;goto done;}
    p->data=dma_alloc_noncoherent(q->tx->device->dev,p->capacity,&p->dma,DMA_TO_DEVICE,GFP_KERNEL);
    if(!p->data){p->capacity=0;ret=-ENOMEM;goto done;}
    q->program_memory+=p->capacity;
    dma_sync_single_for_cpu(q->tx->device->dev,p->dma,p->capacity,DMA_TO_DEVICE);
    memset(p->data,0,p->capacity);
    if(copy_from_user(p->data,u64_to_user_ptr(r.prefix_pointer),r.prefix_bytes)){ret=-EFAULT;goto discard;}
    n=get_unaligned_le32((u8*)p->data+16)>>16;
    if(!n || n>8 || r.prefix_bytes!=qn_stream_prefix_bytes(n) ||
       get_unaligned_le32((u8*)p->data+8)!=256 ||
       (get_unaligned_le32((u8*)p->data+16)&0xffff)){ret=-EINVAL;goto discard;}
    /* Validate once using a complete synthetic zero-activation packet.
     * The kernel copy becomes immutable; later userspace changes cannot
     * change its descriptors, weights, lookup tables or quantization. */
    put_unaligned_le32(256|(1U<<16),(u8*)p->data+8);
    ret=qn_cache_validate(p->data,r.prefix_bytes+4096,4128,&command);
    if(ret)goto discard;
    p->header_bytes=ALIGN(32,alignment);
    p->tail_offset=round_down(r.prefix_bytes,alignment);
    if(p->header_bytes>=p->tail_offset){ret=-EINVAL;goto discard;}
    p->bytes=r.prefix_bytes;p->stages=n;p->tag=command.tag;
    p->owner=file;p->handle=++q->next_program;
    dma_sync_single_for_device(q->tx->device->dev,p->dma,p->capacity,DMA_TO_DEVICE);
    dma_sync_single_range_for_cpu(q->tx->device->dev,p->dma,0,p->header_bytes,DMA_TO_DEVICE);
    dma_sync_single_range_for_cpu(q->tx->device->dev,p->dma,p->tail_offset,p->capacity-p->tail_offset,DMA_TO_DEVICE);
    r.handle=p->handle;
    if(copy_to_user((void __user *)arg,&r,sizeof(r))){ret=-EFAULT;goto discard;}
    ret=0;goto done;
discard:
    qn_program_free(q,p);
done:
    mutex_unlock(&q->lock);return ret;
}

static int qn_release(struct inode *inode, struct file *file)
{
	unsigned slot;
	struct qn_tile *q = file->private_data;
	mutex_lock(&q->lock);
    if(!q->removed && !q->poisoned){
        for(slot=0;slot<QN_STREAM_PROGRAMS;slot++)
            if(q->programs[slot].owner==file)qn_program_free(q,&q->programs[slot]);
    }
	for(slot=0;slot<32;slot++)if(q->slot_owner[slot]==file){q->slot_owner[slot]=NULL;q->slot_dw_valid[slot]=false;}
	if (q->cache_owner == file) {
		q->cache_owner = NULL;
		q->dw_valid = false;
	}
	mutex_unlock(&q->lock);
	kref_put(&q->refs, qn_free);
	return 0;
}

static long qn_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct qn_tile *q = file->private_data;
	struct qn_tile_request req;
	struct qn_tile_batch_request batch;
	struct qn_layer_request layer;
	struct qn_layer_batch_request layer_batch;
    struct qn_stream_run stream;
    struct qn_stream_program *program=NULL;
    u32 tail_bytes=0;
    void *input=q->input;
    dma_addr_t input_dma=q->input_dma;
	struct dma_async_tx_descriptor *desc;
	dma_cookie_t tx_cookie = 0, rx_cookie = 0;
	u64 input_pointer, output_pointer;
	u32 packet_bytes, count, input_bytes, output_bytes, rx_stride, k, i;
	u32 layer_op = 0, layer_m = 0, layer_tag = 0, layer_k = 0;
	bool cached_batch = cmd == QN_LAYER_RUN_BATCH;
    bool registered = cmd == QN_STREAM_RUN;
	bool cached = cmd == QN_LAYER_EXCHANGE || cached_batch || registered;
	bool dma_owned = false;
	int ret, status;
 unsigned layer_slot=0;
	/* The retained-input image supports QNC2, not the original QNT1 protocol. */
    if(cmd==QN_STREAM_REGISTER || cmd==QN_STREAM_RELEASE)
        return qn_program_ioctl(file,cmd,arg);
    if (cmd != QN_LAYER_EXCHANGE && !registered)
		return -ENOTTY;

    if(registered){
        if(copy_from_user(&stream,(void __user *)arg,sizeof(stream)))return -EFAULT;
        if(qn_stream_run_bounds(&stream))return -EINVAL;
        input_pointer=stream.input_pointer;output_pointer=stream.output_pointer;
        packet_bytes=0;count=1;layer.output_bytes=stream.output_bytes;
    }else if (cmd == QN_TILE_RUN) {
		if (copy_from_user(&req, (void __user *)arg, sizeof(req)))
			return -EFAULT;
		if (req.reserved)
			return -EINVAL;
		input_pointer = req.input_pointer;
		output_pointer = req.output_pointer;
		packet_bytes = req.input_bytes;
		count = 1;
	} else if (cmd == QN_TILE_RUN_BATCH) {
		if (copy_from_user(&batch, (void __user *)arg, sizeof(batch)))
			return -EFAULT;
		input_pointer = batch.input_pointer;
		output_pointer = batch.output_pointer;
		packet_bytes = batch.packet_bytes;
		count = batch.count;
	} else if (cached_batch) {
		if (copy_from_user(&layer_batch, (void __user *)arg, sizeof(layer_batch)))
			return -EFAULT;
		if (layer_batch.reserved || qn_layer_batch_bounds(layer_batch.packet_bytes,
		    layer_batch.response_bytes, layer_batch.count))
			return -EINVAL;
		input_pointer = layer_batch.input_pointer;
		output_pointer = layer_batch.output_pointer;
		packet_bytes = layer_batch.packet_bytes;
		count = layer_batch.count;
	} else if (cached) {
		if (copy_from_user(&layer, (void __user *)arg, sizeof(layer)))
			return -EFAULT;
		if (layer.flags || layer.reserved || layer.input_bytes < 16 ||
		    layer.input_bytes > QN_TILE_BATCH_INPUT_BYTES ||
		    layer.output_bytes < 16 || layer.output_bytes > QN_LAYER_BATCH_OUTPUT_BYTES)
			return -EINVAL;
		input_pointer = layer.input_pointer;
		output_pointer = layer.output_pointer;
		packet_bytes = layer.input_bytes;
		count = 1;
	} else {
		return -ENOTTY;
	}
	if (!cached && (!count || count > QN_TILE_MAX_BATCH || packet_bytes < 48 ||
	    packet_bytes > QN_TILE_MAX_INPUT))
		return -EINVAL;
	/* Bounds above make both multiplications safe in u32. */
	input_bytes = count * packet_bytes;
	rx_stride = cached_batch ? layer_batch.response_bytes :
		(cached ? layer.output_bytes : QN_TILE_OUTPUT_BYTES);
	output_bytes = count * rx_stride;
	ret = mutex_lock_interruptible(&q->lock);
	if (ret)
		return ret;
	if (q->removed || q->poisoned || q->needs_rebind) {
		ret = q->removed ? -ENODEV : -EIO;
		goto unlock;
	}
    if(registered){
        program=qn_program_find(q,file,stream.handle);
        if(!program){ret=-ESTALE;goto unlock;}
        input=program->data;input_dma=program->dma;
        input_bytes=packet_bytes=program->bytes+stream.input_bytes;
        tail_bytes=ALIGN(input_bytes,dma_get_cache_alignment())-program->tail_offset;
        put_unaligned_le32(256|(stream.times<<16),(u8*)input+8);
        put_unaligned_le32(stream.valid_times|(program->stages<<16),(u8*)input+16);
        if(copy_from_user((u8*)input+program->bytes,u64_to_user_ptr(input_pointer),stream.input_bytes)){
            ret=-EFAULT;goto unlock;
        }
    }else if (copy_from_user(input, u64_to_user_ptr(input_pointer), input_bytes)) {
		ret = -EFAULT;
		goto unlock;
	}
	/* Validate every packet before any descriptor is queued. */
    if(registered){
        layer_op=17;layer_k=layer_m=256;layer_tag=program->tag;
    }else if (cached) {
		struct qn_layer_command command;
        ret=qn_cache_validate(input,packet_bytes,rx_stride,&command);
        if(ret)goto unlock;
        layer_op=command.op;layer_k=command.k;layer_m=command.m;layer_tag=command.tag;
        layer_slot=((u8*)input)[5];
        if(layer_op==15) {
          unsigned n=get_unaligned_le32((u8*)input+16)>>16, j;
          for(j=0;j<n;j++) {
            u8 *d=(u8*)input+32+j*16;unsigned s=d[0];u32 tag=get_unaligned_le32(d+4);
            if(q->slot_owner[s]!=file || q->slot_tag[s]!=tag || !q->slot_dw_valid[s]){
              ret=-ESTALE;goto unlock;
            }
          }
        } else if(layer_op!=17 && layer_op!=12 && (q->slot_owner[layer_slot]!=file ||
           q->slot_tag[layer_slot]!=layer_tag || (layer_op==14 && !q->slot_dw_valid[layer_slot]))){
            ret=-ESTALE;goto unlock;
        }
        if(layer_op==12){q->slot_owner[layer_slot]=NULL;q->slot_dw_valid[layer_slot]=false;}
        if(layer_op==13)q->slot_dw_valid[layer_slot]=false;
	} else for (i = 0; i < count; i++) {
		u8 *header = (u8 *)input + i * packet_bytes;
		k = get_unaligned_le32(header + 4);
		if (get_unaligned_le32(header) != 0x31544e51 || k < 1 || k > 1024 ||
		    packet_bytes != 16 + 32 * k || get_unaligned_le64(header + 8)) {
			ret = -EINVAL;
			goto unlock;
		}
	}
	/* Legacy MAC operations destroy the cached weights in the shared RTL. */
	if (!cached) {
		q->cache_owner = NULL;
		q->dw_valid = false;
	}
	reinit_completion(&q->tx_done);
	reinit_completion(&q->rx_done);
	/* Cacheable DMA allocations retain their mapping. Transfer ownership
	 * explicitly; the separate page allocations avoid shared cache lines.
	 * Every RX packet must complete fully before its bytes are inspected. */
    if(registered){
        dma_sync_single_range_for_device(q->tx->device->dev,input_dma,0,program->header_bytes,DMA_TO_DEVICE);
        dma_sync_single_range_for_device(q->tx->device->dev,input_dma,program->tail_offset,
            tail_bytes,DMA_TO_DEVICE);
    }else dma_sync_single_for_device(q->tx->device->dev,input_dma,input_bytes,DMA_TO_DEVICE);
	dma_sync_single_for_device(q->rx->device->dev, q->output_dma,
		output_bytes, DMA_FROM_DEVICE);
	dma_owned = true;
	dma_wmb();
	/* Separate descriptors preserve one RX/TX packet boundary per tile.
	 * Submit the complete chains before issue_pending so AXI DMA coalesces
	 * count (<=128) packets rather than issuing one interrupt per tile. */
	for (i = 0; i < count; i++) {
		q->rx_result[i].failed = false;
		q->rx_result[i].done = i == count - 1 ? &q->rx_done : NULL;
		desc = dmaengine_prep_slave_single(q->rx,
			q->output_dma + i * rx_stride, rx_stride,
			DMA_DEV_TO_MEM, DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
		if (!desc) {
			ret = -EIO;
			goto recover;
		}
		desc->callback_result = qn_callback;
		desc->callback_param = &q->rx_result[i];
		rx_cookie = dmaengine_submit(desc);
		if (dma_submit_error(rx_cookie)) {
			ret = rx_cookie;
			goto recover;
		}
	}
	for (i = 0; i < count; i++) {
		q->tx_result[i].failed = false;
		q->tx_result[i].done = i == count - 1 ? &q->tx_done : NULL;
		desc = dmaengine_prep_slave_single(q->tx,
			input_dma + i * packet_bytes, packet_bytes,
			DMA_MEM_TO_DEV, DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
		if (!desc) {
			ret = -EIO;
			goto recover;
		}
		desc->callback_result = qn_callback;
		desc->callback_param = &q->tx_result[i];
		tx_cookie = dmaengine_submit(desc);
		if (dma_submit_error(tx_cookie)) {
			ret = tx_cookie;
			goto recover;
		}
	}
	dma_async_issue_pending(q->rx);
	dma_async_issue_pending(q->tx);
	if (!wait_for_completion_timeout(&q->tx_done, msecs_to_jiffies(5000)) ||
	    !wait_for_completion_timeout(&q->rx_done, msecs_to_jiffies(5000))) {
		ret = -ETIMEDOUT;
		goto recover;
	}
	if (dma_async_is_tx_complete(q->tx, tx_cookie, NULL, NULL) != DMA_COMPLETE ||
	    dma_async_is_tx_complete(q->rx, rx_cookie, NULL, NULL) != DMA_COMPLETE) {
		ret = -EIO;
		goto recover;
	}
	/* Ordered channel callbacks precede the final completion notification. */
	for (i = 0; i < count; i++) {
		if (q->tx_result[i].failed || q->rx_result[i].failed) {
			ret = -EIO;
			goto recover;
		}
	}
    if(registered){
        dma_sync_single_range_for_cpu(q->tx->device->dev,input_dma,0,program->header_bytes,DMA_TO_DEVICE);
        dma_sync_single_range_for_cpu(q->tx->device->dev,input_dma,program->tail_offset,
            tail_bytes,DMA_TO_DEVICE);
    }else dma_sync_single_for_cpu(q->tx->device->dev,input_dma,input_bytes,DMA_TO_DEVICE);
	dma_sync_single_for_cpu(q->rx->device->dev, q->output_dma,
		output_bytes, DMA_FROM_DEVICE);
	dma_owned = false;
	status = gpiod_get_value_cansleep(q->error);
	if (status) {
		ret = status < 0 ? status : -EIO;
		goto recover_completed;
	}
	dma_rmb();
	if (cached) {
		for (i = 0; i < count; i++) {
			u8 *response = (u8 *)q->output + i * rx_stride;
			if (get_unaligned_le32(response) != QN_LAYER_RESPONSE_MAGIC ||
			    get_unaligned_le32(response + 8) != (layer_k | (layer_m << 16)) ||
			    get_unaligned_le32(response + 12) != layer_tag) {
				ret = -EPROTO;
				goto recover_completed;
			}
			if (get_unaligned_le32(response + 4)) {
				ret = -EIO;
				goto recover_completed;
			}
		}
        if(layer_op==13)q->slot_dw_valid[layer_slot]=true;
        if(layer_op==12){q->slot_owner[layer_slot]=file;q->slot_tag[layer_slot]=layer_tag;}

	}
	ret = copy_to_user(u64_to_user_ptr(output_pointer), q->output,
		output_bytes) ? -EFAULT : 0;
	goto unlock;
recover_completed:
	/* Both directions and every callback completed successfully. Only reset
	 * the protocol core: terminating each AXI DMA channel resets shared
	 * hardware and can clear the other channel's interrupt enable bits.
	 * https://github.com/torvalds/linux/blob/v6.8/drivers/dma/xilinx/xilinx_dma.c
	 */
	qn_reset(q);
	goto unlock;
recover:
	if (qn_stop(q))
		ret = -EIO;
	/* An interrupted DMA transaction needs application reactivation to
	 * restore both channel interrupts. Do not repeatedly submit to it. Safe
	 * successful termination still permits normal module/overlay removal. */
	q->needs_rebind = true;
unlock:
	if (dma_owned && !q->poisoned) {
		/* Successful termination returned ownership even on an error. Never
		 * touch quarantined memory while a failed termination may retain it. */
        if(registered){
            dma_sync_single_range_for_cpu(q->tx->device->dev,input_dma,0,program->header_bytes,DMA_TO_DEVICE);
            dma_sync_single_range_for_cpu(q->tx->device->dev,input_dma,program->tail_offset,
                tail_bytes,DMA_TO_DEVICE);
        }else dma_sync_single_for_cpu(q->tx->device->dev,input_dma,input_bytes,DMA_TO_DEVICE);
		dma_sync_single_for_cpu(q->rx->device->dev, q->output_dma,
			output_bytes, DMA_FROM_DEVICE);
	}
	mutex_unlock(&q->lock);
	return ret;
}

#ifdef CONFIG_COMPAT
static long qn_compat_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	return qn_ioctl(file, cmd, (unsigned long)compat_ptr(arg));
}
#endif

static const struct file_operations qn_fops = {
	.owner = THIS_MODULE,
	.open = qn_open,
	.release = qn_release,
	.unlocked_ioctl = qn_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = qn_compat_ioctl,
#endif
	.llseek = no_llseek,
};

static int qn_probe(struct platform_device *pdev)
{
	struct qn_tile *q;
	int ret;
	q = kzalloc(sizeof(*q), GFP_KERNEL);
	if (!q)
		return -ENOMEM;
	q->dev = get_device(&pdev->dev);
	kref_init(&q->refs);
	mutex_init(&q->lock);
	init_completion(&q->tx_done);
	init_completion(&q->rx_done);
	q->reset = devm_gpiod_get(&pdev->dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(q->reset)) {
		ret = PTR_ERR(q->reset);
		goto free_q;
	}
	q->error = devm_gpiod_get(&pdev->dev, "error", GPIOD_IN);
	if (IS_ERR(q->error)) {
		ret = PTR_ERR(q->error);
		goto free_q;
	}
	q->tx = dma_request_chan(&pdev->dev, "tx");
	if (IS_ERR(q->tx)) {
		ret = PTR_ERR(q->tx);
		goto free_q;
	}
	q->rx = dma_request_chan(&pdev->dev, "rx");
	if (IS_ERR(q->rx)) {
		ret = PTR_ERR(q->rx);
		goto release_tx;
	}
	if (!q->tx->device->device_terminate_all || !q->rx->device->device_terminate_all) {
		ret = -EOPNOTSUPP;
		goto release_rx;
	}
	q->input = dma_alloc_noncoherent(q->tx->device->dev, QN_TILE_BATCH_INPUT_BYTES,
		&q->input_dma, DMA_TO_DEVICE, GFP_KERNEL);
	q->output = dma_alloc_noncoherent(q->rx->device->dev, QN_LAYER_BATCH_OUTPUT_BYTES,
		&q->output_dma, DMA_FROM_DEVICE, GFP_KERNEL);
	if (!q->input || !q->output) {
		ret = -ENOMEM;
		goto free_buffers;
	}
	dma_sync_single_for_cpu(q->tx->device->dev, q->input_dma,
		QN_TILE_BATCH_INPUT_BYTES, DMA_TO_DEVICE);
	dma_sync_single_for_cpu(q->rx->device->dev, q->output_dma,
		QN_LAYER_BATCH_OUTPUT_BYTES, DMA_FROM_DEVICE);
	qn_reset(q);
	q->misc.minor = MISC_DYNAMIC_MINOR;
	q->misc.name = "qn-tile";
	q->misc.fops = &qn_fops;
	q->misc.parent = &pdev->dev;
	ret = misc_register(&q->misc);
	if (ret)
		goto free_buffers;
	platform_set_drvdata(pdev, q);
	return 0;
free_buffers:
	if (q->output)
		dma_free_noncoherent(q->rx->device->dev, QN_LAYER_BATCH_OUTPUT_BYTES, q->output, q->output_dma, DMA_FROM_DEVICE);
	if (q->input)
		dma_free_noncoherent(q->tx->device->dev, QN_TILE_BATCH_INPUT_BYTES, q->input, q->input_dma, DMA_TO_DEVICE);
release_rx:
	dma_release_channel(q->rx);
release_tx:
	dma_release_channel(q->tx);
free_q:
	kref_put(&q->refs, qn_free);
	return dev_err_probe(&pdev->dev, ret, "tile probe failed\n");
}

static int qn_remove(struct platform_device *pdev)
{
	struct qn_tile *q = platform_get_drvdata(pdev);
    unsigned i;
	/* misc_deregister synchronizes against misc_open; existing FDs own refs. */
	misc_deregister(&q->misc);
	mutex_lock(&q->lock);
	q->removed = true;
	if (qn_stop(q) || q->poisoned) {
		/* Retain the base ref, channels and buffers on unsafe termination. */
		mutex_unlock(&q->lock);
		return 0;
	}
    for(i=0;i<QN_STREAM_PROGRAMS;i++)qn_program_free(q,&q->programs[i]);
	dma_free_noncoherent(q->rx->device->dev, QN_LAYER_BATCH_OUTPUT_BYTES, q->output, q->output_dma, DMA_FROM_DEVICE);
	dma_free_noncoherent(q->tx->device->dev, QN_TILE_BATCH_INPUT_BYTES, q->input, q->input_dma, DMA_TO_DEVICE);
	dma_release_channel(q->rx);
	dma_release_channel(q->tx);
	mutex_unlock(&q->lock);
	kref_put(&q->refs, qn_free);
	return 0;
}

static const struct of_device_id qn_match[] = {
	{ .compatible = "prototype,qn-tile" }, { }
};
MODULE_DEVICE_TABLE(of, qn_match);
static struct platform_driver qn_driver = {
	.probe = qn_probe,
	.remove = qn_remove,
	.driver = { .name = "qn-tile", .of_match_table = qn_match },
};
module_platform_driver(qn_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("QNT1 tile and QNC2 cached-layer AXI DMA client");

/* Read-only capacity marker for matching experimental userspace. */
static unsigned int rx_capacity = QN_LAYER_BATCH_OUTPUT_BYTES;
module_param(rx_capacity, uint, 0444);
static unsigned int quant_protocol = 1;
module_param(quant_protocol, uint, 0444);
static unsigned int cacheable_dma = 1;
module_param(cacheable_dma, uint, 0444);
static unsigned int bulk_protocol = 1;
module_param(bulk_protocol, uint, 0444);

static unsigned int short_cache_protocol = 1;
module_param(short_cache_protocol, uint, 0444);
static unsigned int stream_chain_protocol = 1;
module_param(stream_chain_protocol, uint, 0444);
static unsigned int short_chain_protocol = 0;
module_param(short_chain_protocol, uint, 0444);
static unsigned int registered_stream_protocol = 1;
module_param(registered_stream_protocol, uint, 0444);
