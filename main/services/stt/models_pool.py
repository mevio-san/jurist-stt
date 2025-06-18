from concurrent.futures import ThreadPoolExecutor
import threading
import queue
from .audio_model import STTAudioModel
from enum import Enum
import logging

class AtomicCounter:
    def __init__(self):
        self.lock = threading.Lock()
        self.counter = 0

    def inc(self):
        with self.lock:
            self.counter += 1

    def get(self):
        with self.lock:
            counter = self.counter
        return counter
            
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
            
        
class ModelsPool:
    SHUTDOWN_PRIORITY = -1
    SHUTDOWN_OP       = 0x00
    DATA_PRIORITY     = 1
    DATA_OP           = 0x01
    
    def __init__(self, max_workers):
        logging.getLogger('nemo_logger').setLevel(logging.ERROR)
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers)
        self.pool_policy = PoolAllocationPolicy(max_workers)
        self.in_queues = [queue.PriorityQueue() for _ in range(max_workers)]
        self.out_queues = [queue.Queue() for _ in range(max_workers)]
        self.models = [STTAudioModel() for _ in range(max_workers)]
        self.executor.map(ModelsPool.__worker, list(range(max_workers)), self.models, self.in_queues, self.out_queues)
        self.dummy_counter = AtomicCounter()
    
    def alloc_job(self):        
        return self.pool_policy.alloc()

    def submit_chunk(self, worker_id, chunk):
        self.dummy_counter.inc()
        # Idiotic priority queue implementation, isn't it?
        self.in_queues[worker_id].put((ModelsPool.DATA_PRIORITY, self.dummy_counter.get(), {'op': ModelsPool.DATA_OP, 'data': chunk}))
    
    def close_job(self, worker_id):
        # Idiotic priority queue implementation, isn't it?
        self.in_queues[worker_id].put((ModelsPool.SHUTDOWN_PRIORITY, self.dummy_counter.get(), {'op': ModelsPool.SHUTDOWN_OP}))
        self.pool_policy.free(worker_id)
            
    @staticmethod
    def __worker(id, model, in_queue, out_queue):
        #model = STTAudioModel()
        print(f'Worker #{id} ready')
        while True:
            _, _, cmd = in_queue.get()
            
            if cmd['op'] == ModelsPool.SHUTDOWN_OP:
                while not in_queue.empty():
                    in_queue.get()
                model.reset_cache()
                print('resetting cache')
                last_transcription = ''
            elif cmd['op'] == ModelsPool.DATA_OP:
                chunk = cmd['data']
                model.ingest(chunk)
