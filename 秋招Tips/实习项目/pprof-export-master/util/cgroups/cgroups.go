// Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

// go:build linux
//  +build linux

package cgroups

import (
	"sync"

	"golang.org/x/sys/unix"

	"pprof-export/log"
)

const unifiedMountPoint = "/sys/fs/cgroup"

var isUnifiedOnce sync.Once
var isUnified bool

var GetMemoryCgroupPaths = func() (memInUsePath, memLimitPath, memStatPath string) {
	if IsCgroup2UnifiedMode() {
		return unifiedMountPoint + "/memory.current", unifiedMountPoint + "/memory.max", unifiedMountPoint + "/memory.stat"
	}
	return unifiedMountPoint + "/memory/memory.usage_in_bytes", unifiedMountPoint + "/memory/memory.limit_in_bytes", unifiedMountPoint + "/memory/memory.stat"
}

var IsCgroup2UnifiedMode = func() bool {
	isUnifiedOnce.Do(func() {
		var st unix.Statfs_t
		err := unix.Statfs(unifiedMountPoint, &st)
		if err != nil {
			log.Errorf("statfs path error: %v", err)
		}
		isUnified = st.Type == unix.CGROUP2_SUPER_MAGIC
	})
	return isUnified
}
