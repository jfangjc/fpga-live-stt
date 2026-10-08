// SPDX-License-Identifier: GPL-2.0
/* Draft AXI DMAengine client for the standalone QNT1 tile. */
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

struct qn_tile {
	struct device *dev;
	struct miscdevice misc;
	struct kref refs;
	struct mutex lock;
	struct dma_chan *tx, *rx;
	struct gpio_desc *reset, *error;
	struct completion tx_done, rx_done;
	void *input, *output;
	dma_addr_t input_dma, output_dma;
	bool removed, poisoned;
};

static void qn_free(struct kref *refs)
{
	struct qn_tile *q = container_of(refs, struct qn_tile, refs);
	put_device(q->dev);
	kfree(q);
}

static void qn_callback(void *arg)
{
	complete(arg);
}

static void qn_reset(struct qn_tile *q)
{
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

static int qn_release(struct inode *inode, struct file *file)
{
	struct qn_tile *q = file->private_data;
	kref_put(&q->refs, qn_free);
	return 0;
}

static long qn_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct qn_tile *q = file->private_data;
	struct qn_tile_request req;
	struct dma_async_tx_descriptor *desc;
	dma_cookie_t tx_cookie, rx_cookie;
	u32 k;
	int ret, status;
	if (cmd != QN_TILE_RUN)
		return -ENOTTY;
	if (copy_from_user(&req, (void __user *)arg, sizeof(req)))
		return -EFAULT;
	if (req.reserved || req.input_bytes < 48 ||
	    req.input_bytes > QN_TILE_MAX_INPUT)
		return -EINVAL;
	ret = mutex_lock_interruptible(&q->lock);
	if (ret)
		return ret;
	if (q->removed || q->poisoned) {
		ret = q->removed ? -ENODEV : -EIO;
		goto unlock;
	}
	if (copy_from_user(q->input, u64_to_user_ptr(req.input_pointer), req.input_bytes)) {
		ret = -EFAULT;
		goto unlock;
	}
	k = get_unaligned_le32((u8 *)q->input + 4);
	if (get_unaligned_le32(q->input) != 0x31544e51 || k < 1 || k > 1024 ||
	    req.input_bytes != 16 + 32 * k ||
	    get_unaligned_le64((u8 *)q->input + 8)) {
		ret = -EINVAL;
		goto unlock;
	}
	reinit_completion(&q->tx_done);
	reinit_completion(&q->rx_done);
	memset(q->output, 0, QN_TILE_OUTPUT_BYTES);
	/* Coherent allocations already have DMA addresses: do not map again. */
	dma_wmb();
	desc = dmaengine_prep_slave_single(q->rx, q->output_dma, QN_TILE_OUTPUT_BYTES,
		DMA_DEV_TO_MEM, DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
	if (!desc) {
		ret = -EIO;
		goto recover;
	}
	desc->callback = qn_callback;
	desc->callback_param = &q->rx_done;
	rx_cookie = dmaengine_submit(desc);
	if (dma_submit_error(rx_cookie)) {
		ret = rx_cookie;
		goto recover;
	}
	dma_async_issue_pending(q->rx);
	desc = dmaengine_prep_slave_single(q->tx, q->input_dma, req.input_bytes,
		DMA_MEM_TO_DEV, DMA_PREP_INTERRUPT | DMA_CTRL_ACK);
	if (!desc) {
		ret = -EIO;
		goto recover;
	}
	desc->callback = qn_callback;
	desc->callback_param = &q->tx_done;
	tx_cookie = dmaengine_submit(desc);
	if (dma_submit_error(tx_cookie)) {
		ret = tx_cookie;
		goto recover;
	}
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
	status = gpiod_get_value_cansleep(q->error);
	if (status) {
		ret = status < 0 ? status : -EIO;
		goto recover;
	}
	dma_rmb();
	ret = copy_to_user(u64_to_user_ptr(req.output_pointer), q->output,
		QN_TILE_OUTPUT_BYTES) ? -EFAULT : 0;
	goto unlock;
recover:
	if (qn_stop(q))
		ret = -EIO;
unlock:
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
	q->input = dma_alloc_coherent(q->tx->device->dev, QN_TILE_MAX_INPUT,
		&q->input_dma, GFP_KERNEL);
	q->output = dma_alloc_coherent(q->rx->device->dev, QN_TILE_OUTPUT_BYTES,
		&q->output_dma, GFP_KERNEL);
	if (!q->input || !q->output) {
		ret = -ENOMEM;
		goto free_buffers;
	}
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
		dma_free_coherent(q->rx->device->dev, QN_TILE_OUTPUT_BYTES, q->output, q->output_dma);
	if (q->input)
		dma_free_coherent(q->tx->device->dev, QN_TILE_MAX_INPUT, q->input, q->input_dma);
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
	/* misc_deregister synchronizes against misc_open; existing FDs own refs. */
	misc_deregister(&q->misc);
	mutex_lock(&q->lock);
	q->removed = true;
	if (qn_stop(q) || q->poisoned) {
		/* Retain the base ref, channels and buffers on unsafe termination. */
		mutex_unlock(&q->lock);
		return 0;
	}
	dma_free_coherent(q->rx->device->dev, QN_TILE_OUTPUT_BYTES, q->output, q->output_dma);
	dma_free_coherent(q->tx->device->dev, QN_TILE_MAX_INPUT, q->input, q->input_dma);
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
MODULE_DESCRIPTION("Draft QNT1 AXI DMA tile client");
