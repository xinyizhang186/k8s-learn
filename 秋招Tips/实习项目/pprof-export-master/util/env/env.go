// Copyright (c) Huawei Technologies Co., Ltd. 2022-2022. All rights reserved.

// Package env provider get env from system
package env

import (
	"os"
	"strconv"
)

// GetEnvAsStringOrDefault returns the env variable for the given key
// or given defaultValue if not set

func GetEnvAsStringOrDefault(key, defaultValue string) string {
	if v:= os.Getenv(key); v !="" {
		return v
	}
	return defaultValue
}

func GetEnvUint64(envKey string, defaultVal uint64) uint64 {
	if val := os.Getenv(envKey); val !="" {
		if v, err := strconv.ParseUint(val, 10, 64); err == nil {
			return v
		} else {
			panic(err)
		}
	}
	return defaultVal
}

func GetEnvFloat64(envKey string, defaultVal float64) float64 {
	if val := os.Getenv(envKey); val !="" {
		if v, err := strconv.ParseFloat(val, 64); err == nil {
			return v
		} else {
			panic(err)
		}
	}
	return defaultVal
}