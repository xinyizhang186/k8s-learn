// Copyright (c) Huawei Technologies Co., Ltd. 2022-2022. All rights reserved.

package env

import (
	"os"
	"testing"
)

func TestGetEnvAsStringOrDefault(t *testing.T) {
	tests := []struct {
		name         string
		key          string
		defaultValue string
		setup        func(string)
		teardown     func(string)
		want         string
	}{
		{
			name:         "env variable is set",
			key:          "TEST_STRING_KEY",
			defaultValue: "default",
			setup: func(key string) {
				os.Setenv(key, "actual_value")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: "actual_value",
		},
		{
			name:         "env variable is empty",
			key:          "TEST_STRING_EMPTY",
			defaultValue: "default",
			setup: func(key string) {
				os.Setenv(key, "")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: "default",
		},
		{
			name:         "env variable is not set",
			key:          "TEST_STRING_NOT_SET",
			defaultValue: "default",
			setup:        func(key string) {},
			teardown:     func(key string) {},
			want:         "default",
		},				
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.setup(tt.key)
			defer tt.teardown(tt.key)
			got := GetEnvAsStringOrDefault(tt.key, tt.defaultValue)
			if got != tt.want {
				t.Errorf("GetEnvAsStringOrDefault() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetEnvUint64(t *testing.T) {
	tests := []struct {
		name       string
		key        string
		defaultVal uint64
		setup      func(string)
		teardown   func(string)
		want       uint64
	}{
		{
			name:       "env variable is set and valid",
			key:        "TEST_UINT64_VALID",
			defaultVal: 100,
			setup: func(key string) {
				os.Setenv(key, "42")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 42,
		},
		{
			name:       "env variable is set and zero",
			key:        "TEST_UINT64_ZERO",
			defaultVal: 100,
			setup: func(key string) {
				os.Setenv(key, "0")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 0,
		},
		{
			name:       "env variable is not set",
			key:        "TEST_UINT64_NOT_SET",
			defaultVal: 100,
			setup:      func(key string) {},
			teardown:   func(key string) {},
			want:       100,
		},	
		{
			name:       "env variable is empty",
			key:        "TEST_UINT64_EMPTY",
			defaultVal: 100,
			setup: func(key string) {
				os.Setenv(key, "")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 100,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.setup(tt.key)
			defer tt.teardown(tt.key)
			got := GetEnvUint64(tt.key, tt.defaultVal)
			if got != tt.want {
				t.Errorf("GetEnvUint64() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetEnvUint64_InvalidValue(t *testing.T) {
	key := "TEST_UINT64_INVALID"
	os.Setenv(key, "not_a_number")
	defer os.Unsetenv(key)

	defer func() {
		if r := recover(); r == nil {
			t.Errorf("GetEnvUint64() expected panic for invalid value")
		}
	}()
	GetEnvUint64(key, 100)
}

func TestGetEnvUint64_NegativeValue(t *testing.T) {
	key := "TEST_UINT64_NEGATIVE"
	os.Setenv(key, "-10")
	defer os.Unsetenv(key)

	defer func() {
		if r := recover(); r == nil {
			t.Errorf("GetEnvUint64() expected panic for negative value")
		}
	}()
	GetEnvUint64(key, 100)
}

func TestGetEnvFloat64(t *testing.T) {
	tests := []struct {
		name       string
		key        string
		defaultVal float64
		setup      func(string)
		teardown   func(string)
		want       float64
	}{
		{
			name:       "env variable is set and valid",
			key:        "TEST_FLOAT64_VALID",
			defaultVal: 100.0,
			setup: func(key string) {
				os.Setenv(key, "3.14")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 3.14,
		},
		{
			name:       "env variable is set and zero",
			key:        "TEST_FLOAT64_ZERO",
			defaultVal: 100.0,
			setup: func(key string) {
				os.Setenv(key, "0.0")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 0.0,
		},
		{
			name:       "env variable is not set",
			key:        "TEST_FLOAT64_NOT_SET",
			defaultVal: 100.0,
			setup:      func(key string) {},
			teardown:   func(key string) {},
			want:       100.0,
		},
		{
			name:       "env variable is empty",
			key:        "TEST_FLOAT64_EMPTY",
			defaultVal: 100.0,
			setup: func(key string) {
				os.Setenv(key, "")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 100.0,
		},
		{
			name:       "env variable is negative",
			key:        "TEST_FLOAT64_NEGATIVE",
			defaultVal: 100.0,
			setup: func(key string) {
				os.Setenv(key, "-2.5")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: -2.5,
		},
		{
			name:       "env variable is scientific notation",
			key:        "TEST_FLOAT64_SCI",
			defaultVal: 100.0,
			setup: func(key string) {
				os.Setenv(key, "1e10")
			},
			teardown: func(key string) {
				os.Unsetenv(key)
			},
			want: 1e10,
		},						
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tt.setup(tt.key)
			defer tt.teardown(tt.key)
			got := GetEnvFloat64(tt.key, tt.defaultVal)
			if got != tt.want {
				t.Errorf("GetEnvFloat64() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestGetEnvFloat64_InvalidValue(t *testing.T) {
	key := "TEST_FLOAT64_INVALID"
	os.Setenv(key, "not_a_float")
	defer os.Unsetenv(key)

	defer func() {
		if r := recover(); r == nil {
			t.Errorf("GetEnvFloat64() expected panic for invalid value")
		}
	}()
	GetEnvFloat64(key, 100.0)
}

func TestGetEnvFloat64_IntValue(t *testing.T) {
	key := "TEST_FLOAT64_INT"
	os.Setenv(key, "42")
	defer os.Unsetenv(key)

	got := GetEnvFloat64(key, 100.0)
	if got != 42.0 {
		t.Errorf("GetEnvFloat64() = %v, want %v", got, 42.0)
	}
}
