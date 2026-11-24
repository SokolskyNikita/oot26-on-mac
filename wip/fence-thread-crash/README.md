# KI-30: SIGSEGV in the GPU fence thread

One crash of the pinned build (`gold-a1ee50a6ef`), 2026-11-23 20:03:52, 67 s into a first boot of a harness run
(a sloperinaGZ test plugin in a private data root): `EXC_BAD_ACCESS` at `0x4545d0157d80aa15`, a non-canonical address,
on `GPUFencingThread`:

```
Vulkan::SamplesStreamer::PopUnsyncedQueries()
VideoCommon::QueryCacheBase<Vulkan::QueryCacheParams>::PopAsyncFlushes()
VideoCommon::FenceManager<Vulkan::FenceManagerParams>::ReleaseThreadFunc(std::stop_token)
```

The pointer read looks like freed or overwritten memory: a query list popped by the fence thread while another
thread changes it is the first thing to check. The log's last second is ordinary loading (pipeline builds, unmapped
device reads also seen in clean boots). The harness retried and the second boot was clean. Not investigated.

Local, not tracked: `local/lichii-2026-11-23-200352.ips` (the crash report) and `local/eden_log-first-boot.txt`.
