// Copyright (c) Huawei Technologies Co., Ltd. 2026-2026. All rights reserved.

// go:build linux
//  +build linux

package cgroups

import (
	"os"
	"testing"
)

const (
	cgroupV1Path = "/sys/fs/cgroup/cpu"
	cgroupV2Path = "/sys/fs/cgroup/cgroup.controllers"
)

func TestIsCgroup2UnifiedMode(t *testing.T) {
	isCgroupV2 := IsCgroup2UnifiedMode()
	if isCgroupV2 {
		if !IsPathExist(cgroupV2Path) {
			t.Fatalf("current os is cgroupv1")
		}
	} else {
		if !IsPathExist(cgroupV1Path) {
			t.Fatalf("current os is cgroupv2")
		}
	}
}

func IsPathExist(path string) bool {
	_, err := os.Stat(path)
	if err == nil {
		return true
	}
	if os.IsNotExist(err) {
		return false
	}
	return false
}

func TestGetMemoryCgroupPaths_CgroupV2(t *testing.T) {
	// 保存原始函数并在测试结束后恢复
	originalIsCgroup2UnifiedMode := IsCgroup2UnifiedMode
	defer func() {
		IsCgroup2UnifiedMode = originalIsCgroup2UnifiedMode
	}()

	// Mock isCgroup2UnifiedMode 返回 true (v2 模式)
	IsCgroup2UnifiedMode = func() bool {
		return true
	}

	memInUsePath, memLimitPath, memStatPath := GetMemoryCgroupPaths()

	// 验证 v2 模式的路径
	expectedMemInUsePath := unifiedMountPoint + "/memory.current"
	expectedMemLimitPath := unifiedMountPoint + "/memory.max"
	expectedMemStatPath := unifiedMountPoint + "/memory.stat"

	if memInUsePath != expectedMemInUsePath {
		t.Errorf("memInUsePath: expected %s, got %s", expectedMemInUsePath, memInUsePath)
	}
	if memLimitPath != expectedMemLimitPath {
		t.Errorf("memLimitPath: expected %s, got %s", expectedMemLimitPath, memLimitPath)
	}
	if memStatPath != expectedMemStatPath {
		t.Errorf("memStatPath: expected %s, got %s", expectedMemStatPath, memStatPath)
	}
}

func TestGetMemoryCgroupPaths_CgroupV1(t *testing.T) {
	// 保存原始函数并在测试结束后恢复
	originalIsCgroup2UnifiedMode := IsCgroup2UnifiedMode
	defer func() {
		IsCgroup2UnifiedMode = originalIsCgroup2UnifiedMode
	}()

	// Mock isCgroup2UnifiedMode 返回 false (v1 模式)
	IsCgroup2UnifiedMode = func() bool {
		return false
	}

	memInUsePath, memLimitPath, memStatPath := GetMemoryCgroupPaths()

	// 验证 v1 模式的路径
	expectedMemInUsePath := unifiedMountPoint + "/memory/memory.usage_in_bytes"
	expectedMemLimitPath := unifiedMountPoint + "/memory/memory.limit_in_bytes"
	expectedMemStatPath := unifiedMountPoint + "/memory/memory.stat"

	if memInUsePath != expectedMemInUsePath {
		t.Errorf("memInUsePath: expected %s, got %s", expectedMemInUsePath, memInUsePath)
	}
	if memLimitPath != expectedMemLimitPath {
		t.Errorf("memLimitPath: expected %s, got %s", expectedMemLimitPath, memLimitPath)
	}
	if memStatPath != expectedMemStatPath {
		t.Errorf("memStatPath: expected %s, got %s", expectedMemStatPath, memStatPath)
	}
}
