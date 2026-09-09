package main

import (
	"context"
	"fmt"
	"os"
	"pprof-export/log"
	"pprof-export/pprof"
	"pprof-export/util/cgroups"
	"sync"
	"time"
)

const (
	memoryLimit = 100 * 1024 * 1024
	// cgroup v1 memory 子系统挂载点下的测试 cgroup 路径
	v1TestCgroupPath = "/sys/fs/cgroup/memory/test"
	// cgroup v2 unified 挂载点下的测试 cgroup 路径
	v2TestCgroupPath = "/sys/fs/cgroup/test"
)

type cgroupPaths struct {
	dir       string 
	limitFile string 
	swapFile  string 
	usageFile string
	statFile  string 
}

func v1Paths() cgroupPaths {
	return cgroupPaths{
		dir:       v1TestCgroupPath,
		limitFile: "memory.limit_in_bytes",
		swapFile:  "memory.memsw.limit_in_bytes",
		usageFile: "memory.usage_in_bytes",
		statFile:  "memory.stat",
	}
}

func v2Paths() cgroupPaths {
	return cgroupPaths{
		dir:       v2TestCgroupPath,
		limitFile: "memory.max",
		swapFile:  "memory.swap.max",
		usageFile: "memory.current",
		statFile:  "memory.stat",
	}
}

func detectCgroupPaths() cgroupPaths {
	if cgroups.IsCgroup2UnifiedMode() {
		log.Infof("detected cgroup v2, test cgroup at %s", v2TestCgroupPath)
		return v2Paths()
	}
	log.Infof("detected cgroup v1, test cgroup at %s", v1TestCgroupPath)
	return v1Paths()
}

func setupCgroup() error {
	p := detectCgroupPaths()

	if err := os.MkdirAll(p.dir, 0755); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("create cgroup dir failed: %w", err)
	}

	limitPath := p.dir + "/" + p.limitFile
	if err := os.WriteFile(limitPath, []byte(fmt.Sprintf("%d", memoryLimit)), 0644); err != nil {
		return fmt.Errorf("set %s failed: %w", p.limitFile, err)
	}

	swapPath := p.dir + "/" + p.swapFile
	if err := os.WriteFile(swapPath, []byte(fmt.Sprintf("%d", memoryLimit)), 0644); err != nil {
		log.Warningf("set %s failed (swap accounting may be disabled): %v", p.swapFile, err)
	}

	procsPath := p.dir + "/cgroup.procs"
	if err := os.WriteFile(procsPath, []byte(fmt.Sprintf("%d", os.Getpid())), 0644); err != nil {
		return fmt.Errorf("add process to cgroup failed: %w", err)
	}

	usagePath := p.dir + "/" + p.usageFile
	statPath := p.dir + "/" + p.statFile
	cgroups.GetMemoryCgroupPaths = func() (memInUsePath, memLimitPath, memStatPath string) {
		return usagePath, limitPath, statPath
	}

	return nil
}

func allocateMemory(stopCh chan struct{}) {
	allocSize := 10 * 1024 * 1024
	blocks := make([][]byte, 0, 10)
	for {
		select {
		case <-stopCh:
			return
		default:
			block := make([]byte, allocSize)
			for i := range block {
				block[i] = 1
			}
			blocks = append(blocks, block)
			time.Sleep(2 * time.Second)
		}
	}
}

func main() {
	if err := setupCgroup(); err != nil {
		log.Error("setup cgroup failed", err)
	}

	pprof.ActivePProf(context.Background(), "test")

	stopCh := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		allocateMemory(stopCh)
	}()

	time.Sleep(30 * time.Second)
	close(stopCh)
	wg.Wait()

	select {}
}
