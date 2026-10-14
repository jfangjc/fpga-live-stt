"""Checkpoint-specific CTC decoding; never infer tokenizer type from model name."""
from pathlib import Path
from citrinet_cpu import decode as wordpiece_decode

def load_decoder(directory):
    directory=Path(directory)
    vocab=(directory/'vocab.txt').read_text().splitlines()
    if not (directory/'tokenizer.model').exists():return vocab,wordpiece_decode
    import sentencepiece as spm
    processor=spm.SentencePieceProcessor(model_file=str(directory/'tokenizer.model'))
    if processor.get_piece_size()!=len(vocab):raise ValueError('Tokenizer/decoder class count mismatch')
    def decode(log_probs,length,_vocab):
        blank=len(vocab);previous=blank;ids=[]
        for index in log_probs[:int(length)].argmax(-1):
            index=int(index)
            if index!=previous and index!=blank:ids.append(index)
            previous=index
        return processor.decode_ids(ids)
    return [processor.id_to_piece(i) for i in range(len(vocab))],decode
