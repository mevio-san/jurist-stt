import audioop
import soxr
import numpy as np

class STTAudioError(Exception):
    pass

class STTAudioEncodingNotSupportedError(STTAudioError):
    pass

class STTAudioChannelsNotSupportedError(STTAudioError):
    pass

class STTAudioAdapter:
    SUPPORTED_ENCODINGS = ['linear16', 'mulaw']
    def __init__(self, encoding, sample_rate_in, channels, sample_rate_out):
        if encoding not in self.SUPPORTED_ENCODINGS:
            raise STTAudioEncodingNotSupportedError('Encoding not supported')
        if channels != 1:
            raise STTAudioChannelsNotSupportedError('Only mono audio is supported')
        
        self._decoder = STTAudioAdapter.__decoder_factory(encoding)
        self._sample_rate_in = sample_rate_in
        self._sample_rate_out = sample_rate_out
        
    @staticmethod
    def __decoder_factory(encoding):
        if encoding == 'mulaw':
            return lambda fragment: np.frombuffer(audioop.ulaw2lin(fragment, 2), dtype=np.int16)
        return lambda fragment: np.frombuffer(fragment, dtype=np.int16)
    
    def transform(self, fragment):
            return soxr.resample(self._decoder(fragment), self._sample_rate_in, self._sample_rate_out)
