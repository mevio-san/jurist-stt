from concurrent.futures import ThreadPoolExecutor
import threading
import queue
from .audio_model import STTAudioModel
from enum import Enum
import logging

class PoolAllocationPolicy:
    def __init__(self, max_workers):
        self.__lock = threading.Lock()
        self.__alloc_bitmap = [False] * max_workers
        self.__max_workers = max_workers 
    
    def alloc(self) -> int:
        with self.__lock:
            try:
                idx = self.__alloc_bitmap.index(False)
                self.__alloc_bitmap[idx] = True
                return idx
            except ValueError:
                return -1

    def free(self, idx) -> bool:
        if (idx < 0) or (idx >= self.__max_workers):
            return False
        with self.__lock:
            self.__alloc_bitmap[idx] = False
        return True
            
        
class ModelsPoolCmds(Enum):
    RESET = 0
    CLOSE = 1

class ModelsPool():
    def __init__(self, max_workers):
        logging.getLogger('nemo_logger').setLevel(logging.ERROR)
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers)
        self.pool_policy = PoolAllocationPolicy(max_workers)
        self.cmds_queues = [queue.Queue() for _ in range(max_workers)]
        self.chunks_queues = [queue.Queue() for _ in range(max_workers)]
        self.output_queues = [queue.Queue() for _ in range(max_workers)]
        self.executor.map(ModelsPool.__worker, list(range(max_workers)), self.cmds_queues, self.chunks_queues, self.output_queues)
    
    def alloc_job(self):        
        return self.pool_policy.alloc()

    def submit_chunk(self, worker_id, chunk):
        self.chunks_queues[worker_id].put(chunk)
    
    def close_job(self, worker_id):
        self.cmds_queues[worker_id].put(ModelsPoolCmds.RESET)
        self.pool_policy.free(worker_id)
            
    @staticmethod
    def __worker(id, cmds_queue, chunks_queue, output_queue):
        model = STTAudioModel()
        print(f'Worker #{id} ready')
        last_transcription = ''
        while True:
            if not cmds_queue.empty():
                cmd = cmds_queue.get()            
                if (cmd == ModelsPoolCmds.RESET):
                    # empties chunks queue
                    while not chunks_queue.empty():
                        chunks_queue.get()
                    model.reset_cache()
                    last_transcription = ''
                elif (cmd == ModelsPoolCmds.CLOSE):
                    break
            print("Waiting for chunks...")
            chunk = chunks_queue.get()
            print(f"received {len(chunk)} bytes (pool)")
            transcription = model.transcribe_chunk(chunk)
            if transcription != last_transcription:
                output_queue.put(transcription)
                last_transcription = transcription

