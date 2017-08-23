import sigrokdecode as srd


class SamplerateError(Exception):
    pass


def normalize_time(t):
    if abs(t) >= 1.0:
        return '%.3f s' % (t,)
    elif abs(t) >= 0.001:
        return '%.3f ms' % (t * 1000.0,)
    elif abs(t) >= 0.000001:
        return '%.3f μs' % (t * 1000.0 * 1000.0,)
    elif abs(t) >= 0.000000001:
        return '%.3f ns' % (t * 1000.0 * 1000.0 * 1000.0,)
    else:
        return '%f' % t


class Decoder(srd.Decoder):
    api_version = 3
    id = 'rc_switch'
    name = 'RC Switch'
    longname = 'RC Switch'
    desc = 'Several RC AC switches, usually working in 433mhz range.'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['rc_switch']
    channels = (
        {'id': 'rc', 'name': 'RC', 'desc': 'RC Input'},
    )
    options = (
        {'id': 'polarity', 'desc': 'Polarity', 'default': 'active-high',
            'values': ('active-low', 'active-high')},
        {'id': 'minPulseLength', 'desc': 'Minimum pulse length μs', 'default': 500},
        {'id': 'minSyncRatio', 'desc': 'Minimum sync/bit ratio in %', 'default': 150},
    )
    annotations = (
        ('bit', 'Bit'),
        ('tri', 'Tri'),
        ('data', 'Data'),
        ('timing', 'Timing'),
        ('warnings', 'Warnings'),
    )
    annotation_rows = (
        ('bits', 'Bits', (0,)),
        ('tris', 'Tris', (1,)),
        ('data', 'Data', (2,)),
        ('timing', 'Timings', (3,)),
        ('warnings', 'Warnings', (4,)),
    )

    def __init__(self):
        self.bit_start = 0
        self.last_edge = 0
        self.last_length = 0
        self.active = None
        self.bits = []

    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        self.active = 0 if self.options['polarity'] == 'active-low' else 1

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value
        minPulseLengthSeconds = self.options['minPulseLength'] / 1000000
        self.minimum_bit_length = int(self.samplerate * minPulseLengthSeconds) - 1

    def parseBits(self):
        length = self.samplenum - self.last_edge
        if self.rc != self.active:
            # Edge in the middle of a pair, just store the position, and length since previous edge
            pass
        elif self.last_length != 0:
            bit_length = self.last_length + length

            if bit_length > self.minimum_bit_length:
                ret = None
                if len(self.bits) > 0 and bit_length / (self.bits[-1][1] - self.bits[-1][0]) > self.options['minSyncRatio'] / 100:
                    ret = 'S'
                elif self.last_length < length:
                    ret = 0
                else:
                    ret = 1

                if ret in (0, 1):
                    self.put(self.samplenum - bit_length, self.samplenum, self.out_ann, [0, ['%d' % ret]])
                if ret == 'S':
                    self.put(self.samplenum - bit_length, self.samplenum, self.out_ann, [0, ['SYNC', 'SYN', 'S']])

                self.bits.append([self.samplenum - bit_length, self.samplenum, ret])

        self.last_length = length
        self.last_edge = self.samplenum

    def handleTris(self):
        bitCount = len(self.bits) - 1
        if bitCount % 2 == 0:
            bits_start = self.bits[0][0]
            triCount = bitCount // 2

            data = ""
            for pos in range(0, triCount):
                index = pos * 2
                bit1 = self.bits[index]
                bit2 = self.bits[index + 1]
                if bit1[2] == 0 and bit2[2] == 0:
                    data += '0'
                    self.put(bit1[0], bit2[1], self.out_ann, [1, ['0']])
                elif bit1[2] == 1 and bit2[2] == 1:
                    data += '1'
                    self.put(bit1[0], bit2[1], self.out_ann, [1, ['1']])
                elif bit1[2] == 0 and bit2[2] == 1:
                    data += 'F'
                    self.put(bit1[0], bit2[1], self.out_ann, [1, ['F']])
                else:
                    data += 'X'
                    self.put(bit1[0], bit2[1], self.out_ann, [1, ['X']])
            self.put(bits_start, self.samplenum, self.out_ann, [2, ['Code Word: ' + data, 'CW: ' + data, 'CW']])

    def handleTimings(self):
        bits_start = self.bits[0][0]

        total0 = 0
        count0 = 0
        total1 = 0
        count1 = 0
        for pos in range(0, len(self.bits) - 1):
            bit = self.bits[pos]
            bitVal = bit[2]
            bitSamples = bit[1] - bit[0]
            if bitVal == 0:
                total0 += bitSamples
                count0 += 1
            else:
                total1 += bitSamples
                count1 += 1
        timingStr = ''
        if count0 > 0:
            timingStr += '0:' + normalize_time((total0 / count0) / self.samplerate)
        if count0 > 0 and count1 > 0:
            timingStr += ', '
        if count1 > 0:
            timingStr += '1: ' + normalize_time((total1 / count1) / self.samplerate)
        syncBit = self.bits[-1]
        syncBitSamples = syncBit[1] - syncBit[0]
        if count0 > 0 or count1 > 0:
            timingStr += ', '
        timingStr += 'S: ' + normalize_time(syncBitSamples / self.samplerate)
        self.put(bits_start, self.samplenum, self.out_ann, [3, [timingStr]])

    def decode(self):
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')
        while True:
            # Wait for any edge (rising or falling).
            (self.rc,) = self.wait({0: 'e'})

            self.parseBits()

            if self.bits and self.bits[-1][2] == 'S':
                self.handleTimings()
                self.handleTris()
                self.bits = []
