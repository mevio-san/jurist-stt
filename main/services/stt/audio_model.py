import copy
import time
import numpy as np
import torch
from threading import Lock
from omegaconf import OmegaConf, open_dict

import nemo.collections.asr as nemo_asr
from nemo.collections.asr.models.ctc_bpe_models import EncDecCTCModelBPE
from nemo.collections.asr.parts.utils.streaming_utils import CacheAwareStreamingAudioBuffer
from nemo.collections.asr.parts.utils.rnnt_utils import Hypothesis

class STTAudioModel:
    SAMPLE_RATE = 16000
    MODEL_NAME = "stt_en_fastconformer_hybrid_large_streaming_1040ms"
    LOOKAHEAD_SIZE = 1040
    DECODER_TYPE = 'rnnt'
    ENCODER_STEP_LENGTH = 80
    MIN_CHUNK_SAMPLES = LOOKAHEAD_SIZE * SAMPLE_RATE // 1000
    
    def __init__(self):
        self.__input_buffer = np.array([], dtype=np.int16)
        self.lock = Lock()
        self.asr_model = nemo_asr.models.ASRModel.from_pretrained(model_name=STTAudioModel.MODEL_NAME)
        self.device = self.asr_model.device
        if STTAudioModel.MODEL_NAME == "stt_en_fastconformer_hybrid_large_streaming_multi":
            if STTAudioModel.LOOKAHEAD_SIZE not in [0, 80, 480, 1040]:
                raise ValueError(
                    f"specified lookahead_size {lookahead_size} is not one of the "
                    "allowed lookaheads (can select 0, 80, 480 or 1040 ms)"
                )
        
        self.left_context_size = self.asr_model.encoder.att_context_size[0]
        self.asr_model.encoder.set_default_att_context_size([self.left_context_size, int(STTAudioModel.LOOKAHEAD_SIZE / STTAudioModel.ENCODER_STEP_LENGTH)])
    
        self.asr_model.change_decoding_strategy(decoder_type=STTAudioModel.DECODER_TYPE)
        
        self.decoding_cfg = self.asr_model.cfg.decoding
        
        with open_dict(self.decoding_cfg):
            self.decoding_cfg.strategy = "greedy"
            self.decoding_cfg.preserve_alignments = False
            if hasattr(self.asr_model, 'joint'):  # if an RNNT model
                self.decoding_cfg.greedy.max_symbols = 10
                self.decoding_cfg.fused_batch_size = -1
            self.asr_model.change_decoding_strategy(self.decoding_cfg)
        
        self.asr_model.eval()

        self.reset_cache()
        
        self.preprocessor = self.__preprocessor_factory(self.asr_model)
        
    def reset_cache(self):
        self.cache_last_channel, self.cache_last_time, self.cache_last_channel_len = self.asr_model.encoder.get_initial_cache_state(
            batch_size=1
        )
        self.__input_buffer = np.array([], dtype=np.int16)
        self.previous_hypotheses = None
        self.pred_out_stream = None
        self.step_num = 0
        self.pre_encode_cache_size = self.asr_model.encoder.streaming_cfg.pre_encode_cache_size[1]
        self.num_channels = self.asr_model.cfg.preprocessor.features
        self.cache_pre_encode = torch.zeros((1, self.num_channels, self.pre_encode_cache_size), device=self.device)
    
    def reset_hyps(self):
        self.previous_hypotheses = None
        self.pred_out_stream = None
        
    @staticmethod
    def __extract_transcriptions(hyps):
        """
            The transcribed_texts returned by CTC and RNNT models are different.
            This method would extract and return the text section of the hypothesis.
        """
        if isinstance(hyps[0], Hypothesis):
            return [hyp.text for hyp in hyps]
        return hyps
    
    # define functions to init audio preprocessor and to
    # preprocess the audio (ie obtain the mel-spectrogram)
    def __preprocessor_factory(self, asr_model):
        self.cfg = copy.deepcopy(self.asr_model._cfg)
        OmegaConf.set_struct(self.cfg.preprocessor, False)

        # some changes for streaming scenario
        self.cfg.preprocessor.dither = 0.0
        self.cfg.preprocessor.pad_to = 0
        self.cfg.preprocessor.normalize = "None"
        
        preprocessor = EncDecCTCModelBPE.from_config_dict(self.cfg.preprocessor)
        preprocessor.to(self.device)
        
        return preprocessor
    
    # returns tuple (processed_signal, processed_signal_length)
    def __preprocess_audio(self, audio, asr_model):
        # doing audio preprocessing
        return self.preprocessor(
            input_signal=torch.from_numpy(audio).unsqueeze_(0).to(self.device),
            length=torch.Tensor([audio.shape[0]]).to(self.device)
        )
    
    def ingest(self, new_chunk):
        with self.lock:
            self.__input_buffer = np.append(self.__input_buffer, new_chunk)
                
    def transcribe(self):
        #self.__input_buffer = np.append(self.__input_buffer, new_chunk)
        with self.lock:
            if len(self.__input_buffer) < STTAudioModel.MIN_CHUNK_SAMPLES:
                return False, None
            
            # get buffered chunk        
            chunk = self.__input_buffer[:STTAudioModel.MIN_CHUNK_SAMPLES]

            # consume the __input_buffer
            self.__input_buffer = self.__input_buffer[STTAudioModel.MIN_CHUNK_SAMPLES:]
            
        # new_chunk (and chunk) is provided as np.int16, so we convert it to np.float32
        # as that is what our ASR models expect
        audio_data = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)
        audio_data = audio_data / 32768.0

        # get mel-spectrogram signal & length
        processed_signal, processed_signal_length = self.__preprocess_audio(audio_data, self.asr_model)
    
        # prepend with cache_pre_encode
        processed_signal = torch.cat([self.cache_pre_encode, processed_signal], dim=-1)
        processed_signal_length += self.cache_pre_encode.shape[1]
        
        # save cache for next time
        self.cache_pre_encode = processed_signal[:, :, -self.pre_encode_cache_size:]
        
        with torch.no_grad():
            (
                self.pred_out_stream,
                transcribed_texts,
                self.cache_last_channel,
                self.cache_last_time,
                self.cache_last_channel_len,
                self.previous_hypotheses,
            ) = self.asr_model.conformer_stream_step(
                processed_signal=processed_signal,
                processed_signal_length=processed_signal_length,
                cache_last_channel=self.cache_last_channel,
                cache_last_time=self.cache_last_time,
                cache_last_channel_len=self.cache_last_channel_len,
                keep_all_outputs=False,
                previous_hypotheses=self.previous_hypotheses,
                previous_pred_out=self.pred_out_stream,
                drop_extra_pre_encoded=None,
                return_transcription=True,
            )
        
        final_streaming_tran = STTAudioModel.__extract_transcriptions(transcribed_texts)
        self.step_num += 1
        
        return True, final_streaming_tran[0]