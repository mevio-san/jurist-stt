import json

class STTMessageOut:
    def __init__(self):
        self.speech_final: bool = False
        self.is_final: bool = False
        self.transcript: str = ''
    
    def finalizeTranscript(self) -> None:
        '''
        Use this method to mark the end on the transcription.
        Make sure that the transcription is not empty before
        calling this method.
        '''
        self.speech_final = True
        self.is_final = True

    def resetTranscript(self) -> None:
        self.transcript = ''
                
    def setTranscript(self, text) -> None:
        self.transcript += text
    
    def toJSON(self):
        obj = {
            'is_final': self.is_final,
            'speech_final': self.speech_final,
        }
        if len(self.transcript) > 0:
            obj['alternatives'] = [
                {
                    'transcript': self.transcript
                }
            ]
        return json.dumps(obj)
