"""External knowledge connectors — feed the thesis layer with real domain data.

Pure quant tells you what *survived past noise*; thesis tells you what you
*believe about the world*. This package wires the second half. Each
connector reads a structured external knowledge source and produces:

  - a short "thesis brief" (markdown summary of key facts + sources)
  - a list of recommended (symbol, catalyst, kill_switch, horizon, conviction)
    tuples the fund.thesis module can auto-attach

Today the only connector is jobsdata — Matt's labor-market AI-impact
project at ~/jobsdata/. The pattern generalizes: any structured research
corpus (jobsdata, second-brain, future macro feeds) gets its own module
under fund/knowledge/ with the same interface.
"""
