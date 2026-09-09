package exporter

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime/pprof"
	"sort"
	"strings"
	"sync"
	"time"

	"pprof-export/log"
	pprofnames "pprof-export/pprof/names"
)

const (
	createIfAbsent     = os.O_WRONLY | os.O_CREATE | os.O_TRUNC
	mode               = 0600
	timeFormat         = "20060102-150405"
	hideDebuggingInfo  = 0
	cpuProfileDuration = 15
	profilingPathPerm  = 0750
	keepRecentCount    = 2
)

type Config struct {
	FilePrefix 	  string
	ProfilingPath string
}

type exporter struct {
	Config
	sync.Mutex
}

func NewExporter(config Config) Exporter {
	return &exporter{Config: config}
}

func (e *exporter) Init() error {
	if err := os.MkdirAll(e.ProfilingPath, profilingPathPerm); err != nil && !os.IsExist(err) {
		return fmt.Errorf("create profilingPath error : %v", err)
	}
	return nil
}

func (e *exporter) Export(scope pprofnames.Scope) {
	e.Lock()
	defer e.Unlock()

	timestamp := time.Now().Format(timeFormat)

	var wg sync.WaitGroup
	for _, profile := range scope {
		wg.Add(1)
		go func(p pprofnames.Name) {
			defer wg.Done()
			e.exportProfile(p, timestamp)
		}(profile)
	}
	wg.Wait()

	e.cleanOldProfileFile()
}

func (e *exporter) exportProfile(name pprofnames.Name, timestamp string) {
	file, err := e.createProfileFile(name.FileExt(), timestamp)
	if err != nil {
		log.Errorf("open %s profiling file error,reason: %v", name.ProfileName(), err)
		return
	}
	defer func() {
		if err := file.Close(); err != nil {
			log.Errorf("close %s profiling file error,reason: %v", name.ProfileName(), err)
		}
	}()

	switch name {
	case pprofnames.CPU:
		e.writeCPUProfile(file, time.Second*cpuProfileDuration)
	case pprofnames.Heap:
		e.writeHeapProfile(file)
	case pprofnames.Block, pprofnames.Mutex, pprofnames.Goroutine:
		e.writeGeneralProfile(file, name.ProfileName())
	default:
		log.Warningf("Unsupported profile %s", name.ProfileName())
	}
}

type profileFile struct {
	path      string
	name      string
	timestamp string
}

func (e *exporter) cleanOldProfileFile() {
	profileFiles, err := e.getAllProfileFiles()
	if err != nil {
		log.Errorf("clean old profile error : %v", err)
		return
	}
	batchesToKeep := e.findBatchToKeep(profileFiles)
	for _, f := range profileFiles {
		if !batchesToKeep[f.timestamp] {
			log.Infof("clean old profile %q", f.name)
			if err := os.Remove(f.path); err != nil && !os.IsNotExist(err) {
				log.Errorf("clean old profile %q error : %v", f.name, err)
			}
		}
	}
}

func (e *exporter) createProfileFile(fileExt, timestamp string) (file *os.File, err error) {
	f := fmt.Sprintf("%s-%s-%s", e.FilePrefix, timestamp, fileExt)
	filePath := filepath.Clean(filepath.Join(e.ProfilingPath, f))
	return os.OpenFile(filePath, createIfAbsent, mode)
}

func (e *exporter) writeCPUProfile(file *os.File, profileInterval time.Duration) {
	log.Infof("trying to generate cpu profiling file")
	if err := pprof.StartCPUProfile(file); err != nil {
		log.Errorf("fail generate cpu profiling file,reason: %v", err)
		return
	}
	defer pprof.StopCPUProfile()
	t := time.NewTimer(profileInterval)
	defer t.Stop()
	<-t.C
}

func (e *exporter) writeHeapProfile(file *os.File) {
	log.Infof("trying to generate heap profiling file")
	if err := pprof.WriteHeapProfile(file); err != nil {
		log.Errorf("fail generate heap profiling file,reason: %v", err)
		return
	}
}

func (e *exporter) writeGeneralProfile(file io.Writer, name string) {
	log.Infof("trying to generate %s profiling file", name)
	profile := pprof.Lookup(name)
	if profile == nil {
		log.Infof("generate %s profiling file error.", name)
		return
	}
	if err := profile.WriteTo(file, hideDebuggingInfo); err != nil {
		log.Errorf("fail generate %s profiling file. %v", name, err)
		return
	}
}

func (e *exporter) getAllProfileFiles() ([]profileFile, error) {
	var profileFiles []profileFile
	err := filepath.Walk(e.ProfilingPath, func(absPath string, fileInfo os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if fileInfo.IsDir() {
			return nil
		}
		if strings.HasPrefix(fileInfo.Name(), e.FilePrefix) && strings.HasSuffix(fileInfo.Name(), ".profile") {
			timestamp := extractTimestamp(fileInfo.Name())
			profileFiles = append(profileFiles, profileFile{path: absPath, name: fileInfo.Name(), timestamp: timestamp})
		}
		return nil
	})
	return profileFiles, err
}

func (e *exporter) findBatchToKeep(profileFiles []profileFile) map[string]bool {
	// find all batches
	batchSet := make(map[string]bool)
	var batches []string
	for _, f := range profileFiles {
		if !batchSet[f.timestamp] {
			batches = append(batches, f.timestamp)
			batchSet[f.timestamp] = true
		}
	}

	// sort batches by timestamp
	sort.Slice(batches, func(i, j int) bool {
		return batches[i] > batches[j]
	})

	// keep recent batches, remove olds
	var batchesToKeep = make(map[string]bool)
	for i := 0; i < keepRecentCount && i < len(batches); i++ {
		batchesToKeep[batches[i]] = true
	}
	return batchesToKeep
}

// file name format: {prefix}-{date}-{time}-{suffix}, consist of 4 parts
func extractTimestamp(fileName string) string {
	baseName := filepath.Base(fileName)
	ext := filepath.Ext(baseName)
	nameWithoutExt := strings.TrimSuffix(baseName, ext)
	parts := strings.Split(nameWithoutExt, "-")
	if len(parts) < 4 {
		return ""
	}
	return parts[1] + "-" + parts[2]
}
