package trigger

import (
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"

	"pprof-export/log"
	"pprof-export/pprof/exporter"
	pprofnames "pprof-export/pprof/names"
	"pprof-export/util/cgroups"
)

const (
	decimalBase		  = 10
	bitSize			  = 64
	kvLength 		  = 2
	alertResetTimeout = 10 * time.Minute
)

var memoryPressurePProfScope = pprofnames.Scope{pprofnames.Heap, pprofnames.Goroutine}

type MemoryPressureConfig struct {
	CheckInterval   time.Duration
	AlertMem        int64
	AlertPercent    float64
	MemoryIncrement float64
}

type memoryPressureTrigger struct {
	MemoryPressureConfig
	exporter exporter.Exporter
}

func NewMemoryPressureTrigger(e exporter.Exporter, config MemoryPressureConfig) Trigger {
	return &memoryPressureTrigger{
		exporter: 			  e,
		MemoryPressureConfig: config,
	}
}

type triggerState struct {
	lastAlertTime    time.Time
	lastExportMemory int64
}

func (m *memoryPressureTrigger) Start(ctx context.Context) {
	ticker := time.NewTicker(m.CheckInterval)
	defer ticker.Stop()

	log.Infof("memory pressure trigger started")

	var state triggerState
	for {
		select {
		case <-ctx.Done():
			log.Infof("memory pressure trigger stopped")
			return
		case <-ticker.C:
			m.exportOnAlert(&state)
		}
	}
}

func (m *memoryPressureTrigger) exportOnAlert(state *triggerState) {
	// 判断是否内存超过阈值
	isOnAlert, memInUsage, memLimit := m.isMemoryOnAlert()
	if !isOnAlert {
		// 上次导出后，持续了一段时间没有再预警，则删除上次导出时内存记录
		if state.lastExportMemory != 0 {
			state.lastAlertTime = fixClockJump(state.lastAlertTime)
			if time.Since(state.lastAlertTime) >= alertResetTimeout {
				state.lastExportMemory = 0
			}
		}
		return
	}

	// 记录最后一次内存预警时间，清除上次导出时内存记录需要借助此时间
	state.lastAlertTime = time.Now()

	// 如果之前导出过，要求当前内存相较上次导出pprof时的内存值有一定的增量才允许再次导出
	if !m.shouldExport(memInUsage, memLimit, state.lastExportMemory) {
		return
	}

	// 导出pprof并记录当前内存统计
	log.Infof("pprof export triggered by memory pressure")
	m.logMemoryStats()
	m.exporter.Export(memoryPressurePProfScope)

	// 记录最后一次导出pprof时内存占用，后续重复内存预警时，参考本次导出时内存决策是否再次导出。
	state.lastExportMemory = memInUsage
}

func (m *memoryPressureTrigger) logMemoryStats() {
	_, _, memStatPath := cgroups.GetMemoryCgroupPaths()
	out, err := os.ReadFile(memStatPath)
	if err != nil {
		log.Warningf("failed to read mem stats : %s", err)
		return
	}
	log.Infof("memory stats: %s", strings.ReplaceAll(string(out), "\n", ","))
}

func (m *memoryPressureTrigger) shouldExport(memInUsage, memLimit, lastExportMemory int64) bool {
	if lastExportMemory == 0 {
		return true
	}
	increasePercent := float64(memInUsage-lastExportMemory) / float64(memLimit)
	return increasePercent >= m.MemoryIncrement
}

func (m *memoryPressureTrigger) isMemoryOnAlert() (bool, int64, int64) {
	memInUsage, memLimit, err := m.getMemoryUsageAndLimit()
	if err != nil {
		log.Warningf("failed to read mem status, Err: %s", err)
		return false, 0, 0
	}

	return m.isOnAlert(memInUsage, memLimit), memInUsage, memLimit
}

func (m *memoryPressureTrigger) isOnAlert(memInUsage, memLimit int64) bool {
	if m.AlertMem > 0 {
		return memLimit-memInUsage < m.AlertMem
	}
	return float64(memInUsage)/float64(memLimit) > m.AlertPercent
}

func (m *memoryPressureTrigger) getMemoryUsageAndLimit() (int64, int64, error) {
	memInUsePath, memLimitPath, memStatPath := cgroups.GetMemoryCgroupPaths()

	memInUsage, err := readFileValue(memInUsePath)
	if err != nil {
		return 0, 0, err
	}

	memLimit, err := readFileValue(memLimitPath)
	if err != nil {
		return 0, 0, err
	}
	if memLimit == 0 {
		return 0, 0, fmt.Errorf("memory limit can not be zero")
	}

	memInactive, err := getInactiveMem(memStatPath)
	if err != nil {
		return 0, 0, err
	}

	finalUsage := int64(memInUsage) - int64(memInactive)
	return finalUsage, int64(memLimit), nil
}

func readFileValue(filePath string) (uint64, error) {
	out, err := os.ReadFile(filePath)
	if err != nil {
		return 0, err
	}
	content := strings.TrimSpace(string(out))
	return strconv.ParseUint(content, decimalBase, bitSize)
}

func getInactiveMem(filePath string) (uint64, error) {
	data, err := os.ReadFile(filePath)
	if err !=  nil {
		return 0, err
	}

	lines := strings.Split(string(data), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "inactive_file") {
			fields := strings.Fields(line)
			if len(fields) != kvLength {
				break
			}
			return strconv.ParseUint(fields[1], decimalBase, bitSize)
		}
	}

	return 0, fmt.Errorf("inactive_file entry not found")
}

func fixClockJump(lastAlertTime time.Time) time.Time {
	now := time.Now()
	if now.Sub(lastAlertTime) < 0 {
		return now
	} else {
		return lastAlertTime
	}
}
