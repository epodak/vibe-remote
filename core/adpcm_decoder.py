class ADPCMDecoder:
    """
    16kHz IMA-ADPCM 逐样点实时解码器
    采用 89 阶步长表与 8 阶索引表，将 4-bit 差值积分还原为 16-bit 线性 PCM
    """
    INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8]
    STEP_TABLE = [
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17,
        19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
        50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
        130, 143, 157, 173, 190, 209, 230, 253, 279, 307,
        337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
        876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
        2272, 2494, 2740, 3008, 3307, 3638, 4002, 4402, 4842, 5327,
        5860, 6446, 7091, 7800, 8580, 9438, 10382, 11420, 12562, 13818,
        15200, 16720, 18392, 20231, 22254, 24479, 26927, 29620, 32767
    ]

    def __init__(self):
        self.predictor = 0
        self.step_index = 0

    def reset(self):
        self.predictor = 0
        self.step_index = 0

    def decode_nibble(self, nibble: int) -> int:
        step = self.STEP_TABLE[self.step_index]
        diff = step >> 3
        if nibble & 4: diff += step
        if nibble & 2: diff += (step >> 1)
        if nibble & 1: diff += (step >> 2)
        if nibble & 8: diff = -diff

        self.predictor = max(-32768, min(32767, self.predictor + diff))
        self.step_index = max(0, min(88, self.step_index + self.INDEX_TABLE[nibble & 7]))
        return self.predictor

    def decode(self, data_bytes: bytes) -> list:
        samples = []
        for b in data_bytes:
            samples.append(self.decode_nibble(b >> 4))
            samples.append(self.decode_nibble(b & 0x0F))
        return samples
