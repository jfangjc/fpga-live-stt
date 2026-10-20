"""Exact supported multilingual GGML architectures and upstream source identities."""
SPECS = {
    'base': {
        'id':'openai/whisper-base',
        'header':(0x67676d6c,51865,1500,512,8,6,448,512,8,6,80),
        'source_sha1':'465707469ff3a37a2b9b8d8f89f2f99de7299dac',
    },
    'small': {
        'id':'openai/whisper-small',
        'header':(0x67676d6c,51865,1500,768,12,12,448,768,12,12,80),
        'source_sha1':'55356645c2b361a969dfd0ef2c5a50d530afd8d5',
    },
    'large-v3-turbo': {
        'id':'openai/whisper-large-v3-turbo',
        'header':(0x67676d6c,51866,1500,1280,20,32,448,1280,20,4,128),
        'source_sha1':'4af2b29d7ec73d781377bfd1758ca957a807e941',
    },
}
