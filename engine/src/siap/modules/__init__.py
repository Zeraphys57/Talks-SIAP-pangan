"""Analysis modules.

Each module is a pure transformation from a price series to scores: it takes a
DataFrame and parameters, and returns a DataFrame. Nothing here touches the
database or the network, which is what lets the detectors be tested against
synthetic series with spikes at known indices.

Persistence and run bookkeeping live in `siap.analyze`.
"""
