class STTChannelTranscript:
    def __init__(self):
        self.transcript: str = ''

class STTChannel:
    def __init__(self):
        self.alternatives: [STTChannelTranscript] = []   

class STTMessageOut:
    def __init__(self):
        self.speech_final: bool = False
        self.is_final: bool = False
        self.channel: STTChannel or None = None
    
    def finalizeTranscription(self) -> None:
        '''
        Use this method to mark the end on the transcription.
        Make sure that the transcription is not empty before
        calling this method.
        '''
        self.speech_final = True
        self.is_final = True
        
    def appendToTranscription(self, text) -> None:
        if not self.channel:
            self.channel.alternatives = [STTChannelTranscript()]
        self.channel.alternatives[0].transcript += text
