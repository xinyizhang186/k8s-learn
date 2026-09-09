package pprof

import (
	"context"
	"time"

	"pprof-export/log"
	"pprof-export/pprof/exporter"
	"pprof-export/pprof/trigger"
	"pprof-export/util/env"
)

const (
	profilingPathEnv = "HW_PROFILING_PATH"
	checkIntervalEnv = "HW_PROFILING_CHECK_INTERVAL"
	// export memory threshold: export when the remaining memory is less than this value
	alertMemEnv = "HW_PROFILING_ALERT_MEM"
	// export memory threshold: export when the memory usage ratio exceeds this value
	alertPercentEnv = "HW_PROFILING_ALERT_PERCENT"
	// continuous export memory increment requirements
	memoryIncrementEnv     = "HW_PROFILING_MEMERY_INCREMENT"
	defaultProfilingPath   = "/opt/dump/coredump"
	defaultCheckInterval   = 1
	defaultAlertPercent    = float64(0.8)
	defaultMemoryIncrement = float64(0.08)
	mib                    = 1024 * 1024
)

func ActivePProf(ctx context.Context, filePrefix string) {
	profilingPath := env.GetEnvAsStringOrDefault(profilingPathEnv, defaultProfilingPath)
	checkInterval := time.Second * time.Duration(env.GetEnvUint64(checkIntervalEnv, defaultCheckInterval))
	alertMem := mib * env.GetEnvUint64(alertMemEnv, 0)
	alertPercent := env.GetEnvFloat64(alertPercentEnv, 0)
	memoryIncrement := env.GetEnvFloat64(memoryIncrementEnv, defaultMemoryIncrement)

	if alertMem <= 0 && alertPercent <= 0 {
		alertPercent = defaultAlertPercent
	}

	// create pprof exporter
	pprofExporter := exporter.NewExporter(exporter.Config{
		FilePrefix:    filePrefix,
		ProfilingPath: profilingPath,
	})

	// init exporter: ensure pprof output directory exists etc.
	if err := pprofExporter.Init(); err != nil {
		log.Error(err)
		return
	}

	// create pprof trigger
	triggers := []trigger.Trigger{
		trigger.NewSignalTrigger(pprofExporter),
		trigger.NewMemoryPressureTrigger(pprofExporter, trigger.MemoryPressureConfig{
			CheckInterval:   checkInterval,
			AlertMem:        int64(alertMem),
			AlertPercent:    alertPercent,
			MemoryIncrement: memoryIncrement,
		}),
	}

	// start trigger
	for _, tr := range triggers {
		go tr.Start(ctx)
	}

	log.Infof("pprof active, profiling path: %s", profilingPath)
}
