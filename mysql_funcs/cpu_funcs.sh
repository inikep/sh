#!/bin/echo This script should be sourced in a shell, not executed directly

function disable_address_randomization(){
    PREVIOUS_ASLR=`cat /proc/sys/kernel/randomize_va_space`
    sudo sh -c "echo 0 > /proc/sys/kernel/randomize_va_space"
    echo "Changing /proc/sys/kernel/randomize_va_space from $PREVIOUS_ASLR to `cat /proc/sys/kernel/randomize_va_space`"
}

function restore_address_randomization(){
    local CURRENT_ASLR=`cat /proc/sys/kernel/randomize_va_space`
    sudo sh -c "echo $PREVIOUS_ASLR > /proc/sys/kernel/randomize_va_space"
    echo "Resoring /proc/sys/kernel/randomize_va_space from $CURRENT_ASLR to `cat /proc/sys/kernel/randomize_va_space`"
}

function disable_turbo_boost(){
  SCALING_DRIVER=`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver`
  echo "Using $SCALING_DRIVER scaling driver"

  if [[ ${SCALING_DRIVER} == "intel_pstate" || ${SCALING_DRIVER} == "intel_cpufreq" ]]; then
    PREVIOUS_TURBO=`cat /sys/devices/system/cpu/intel_pstate/no_turbo`
    sudo sh -c "echo 1 > /sys/devices/system/cpu/intel_pstate/no_turbo"
    echo "Changing /sys/devices/system/cpu/intel_pstate/no_turbo from $PREVIOUS_TURBO to `cat /sys/devices/system/cpu/intel_pstate/no_turbo`"
  else
    PREVIOUS_TURBO=`cat /sys/devices/system/cpu/cpufreq/boost`
    sudo sh -c "echo 0 > /sys/devices/system/cpu/cpufreq/boost"
    echo "Changing /sys/devices/system/cpu/cpufreq/boost from $PREVIOUS_TURBO to `cat /sys/devices/system/cpu/cpufreq/boost`"
  fi
}

function restore_turbo_boost(){
  echo "Restore turbo boost with $SCALING_DRIVER scaling driver"

  if [[ ${SCALING_DRIVER} == "intel_pstate" || ${SCALING_DRIVER} == "intel_cpufreq" ]]; then
    CURRENT_TURBO=`cat /sys/devices/system/cpu/intel_pstate/no_turbo`
    sudo sh -c "echo $PREVIOUS_TURBO > /sys/devices/system/cpu/intel_pstate/no_turbo"
    echo "Resoring /sys/devices/system/cpu/intel_pstate/no_turbo from $CURRENT_TURBO to $PREVIOUS_TURBO"
  else
    CURRENT_TURBO=`cat /sys/devices/system/cpu/cpufreq/boost`
    sudo sh -c "echo $PREVIOUS_TURBO > /sys/devices/system/cpu/cpufreq/boost"
    echo "Resoring /sys/devices/system/cpu/cpufreq/boost from $CURRENT_TURBO to $PREVIOUS_TURBO"
  fi
}

function change_scaling_governor(){
  PREVIOUS_GOVERNOR=`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
  sudo cpupower frequency-set -g $1
  echo "Changing scaling governor from $PREVIOUS_GOVERNOR to `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`"
  sudo cpupower frequency-info
}

function restore_scaling_governor(){
  local CURRENT_GOVERNOR=`cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`
  sudo cpupower frequency-set -g $PREVIOUS_GOVERNOR
  echo "Restoring scaling governor from $CURRENT_GOVERNOR to `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`"
  sudo cpupower frequency-info
}

function disable_idle_states(){
  sudo cpupower idle-set --disable-by-latency 0
  sudo cpupower idle-info
}

function enable_idle_states(){
  sudo cpupower idle-set --enable-all
  sudo cpupower idle-info
}

function stabilize_cpu(){
  LOGS_CPU=${1:-/dev/stdout}
  disable_address_randomization >> ${LOGS_CPU}
  disable_turbo_boost > ${LOGS_CPU}
  change_scaling_governor powersave >> ${LOGS_CPU}
  disable_idle_states >> ${LOGS_CPU}
}

function restore_cpu(){
  LOGS_CPU=${1:-/dev/stdout}
  echo "Restoring address randomization"
  restore_address_randomization >> ${LOGS_CPU}
  echo "Restoring turbo boost"
  restore_turbo_boost >> ${LOGS_CPU}
  echo "Restoring scaling governor"
  restore_scaling_governor >> ${LOGS_CPU}
  echo "Enabling idle states"
  enable_idle_states >> ${LOGS_CPU}
}
