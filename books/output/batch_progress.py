"""Batch work progress independent of unknown or revised provider page counts.

Each chapter download, output render and output write/validation is a work unit.
These units describe workflow progress, not equal durations. The final five
percent belongs to Calibre import/verification; only its terminal owner sets 100.
"""

PREPARED_PERCENT = 95


class BatchProgress:
    def __init__(self, chapter_counts):
        self.counts = tuple(max(0, int(n)) for n in chapter_counts)
        self.offsets = []
        total = 0
        for count in self.counts:
            self.offsets.append(total)
            total += count + 2
        self.total = max(1, total)
        self.value = 0

    def update(self, output, phase, done=0, total=1, chapter=0):
        count = self.counts[output]
        fraction = min(1., max(0., done / max(1, total)))
        if phase == 'download':
            units = min(count, chapter + fraction)
        elif phase == 'render':
            units = count + fraction
        elif phase == 'write':
            units = count + 1
        elif phase == 'settled':
            units = count + 2
        else:
            raise ValueError('Unknown batch progress phase: ' + phase)
        self.value = max(self.value, min(PREPARED_PERCENT,
            int(PREPARED_PERCENT * (self.offsets[output] + units) / self.total)))
        return self.value


def import_percent(accounted, total):
    return PREPARED_PERCENT + min(4, max(0, int(4 * accounted / max(1, total))))
