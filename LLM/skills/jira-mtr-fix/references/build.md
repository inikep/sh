# Building MySQL / Percona Server for Bug Reproduction

## Prerequisites

### Ubuntu / Debian
```bash
sudo apt-get install -y \
  build-essential cmake ninja-build \
  libssl-dev libncurses5-dev libtirpc-dev \
  bison flex pkg-config \
  libaio-dev libreadline-dev \
  zlib1g-dev liblz4-dev libzstd-dev \
  libcurl4-openssl-dev \
  python3 python3-dev \
  libudev-dev libsystemd-dev \
  libldap2-dev libsasl2-dev \
  libre2-dev libprotobuf-dev protobuf-compiler \
  libkrb5-dev
```

### RHEL / CentOS / Rocky
```bash
sudo yum install -y \
  cmake gcc gcc-c++ make ninja-build \
  openssl-devel ncurses-devel tirpc-devel \
  bison flex pkgconfig \
  libaio-devel readline-devel \
  zlib-devel lz4-devel libzstd-devel \
  libcurl-devel \
  python3 python3-devel \
  systemd-devel \
  openldap-devel cyrus-sasl-devel \
  re2-devel protobuf-devel protobuf-compiler \
  krb5-devel
```

## Boost

Percona/MySQL requires a specific Boost version (typically 1.77 or 1.79).
Check `cmake/boost.cmake` in the source for the required version.

```bash
# Download and extract (example for 1.77.0)
BOOST_VER=1_77_0
wget https://boostorg.jfrog.io/artifactory/main/release/1.77.0/source/boost_${BOOST_VER}.tar.bz2
tar xjf boost_${BOOST_VER}.tar.bz2
export BOOST_DIR=$(pwd)/boost_${BOOST_VER}
```

Alternatively, let cmake download it automatically:
```bash
-DDOWNLOAD_BOOST=1 -DWITH_BOOST=/tmp/boost_download
```

## CMake Configuration Options

### Debug build (recommended for bug reproduction)
```bash
cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DWITH_DEBUG=1 \
  -DWITH_ASAN=0 \
  -DWITH_UBSAN=0 \
  -DWITH_BOOST=${BOOST_DIR} \
  -DWITH_UNIT_TESTS=0 \
  -DWITH_RAPID=0 \
  -DWITH_ROUTER=0 \
  -DMYSQL_MAINTAINER_MODE=0
```

### With AddressSanitizer (for memory bugs)
```bash
cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DWITH_DEBUG=1 \
  -DWITH_ASAN=1 \
  -DWITH_BOOST=${BOOST_DIR} \
  -DWITH_UNIT_TESTS=0
```

### With Valgrind support
```bash
cmake .. \
  -DCMAKE_BUILD_TYPE=Debug \
  -DWITH_DEBUG=1 \
  -DWITH_VALGRIND=1 \
  -DWITH_BOOST=${BOOST_DIR}
```

### Release build (for performance-related bugs)
```bash
cmake .. \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DWITH_BOOST=${BOOST_DIR} \
  -DWITH_UNIT_TESTS=0
```

## Build Commands

```bash
# Full build
make -j$(nproc) mysqld mysql mysql_install_db

# Incremental (after source change)
make -j$(nproc) mysqld

# Just the plugin or storage engine
make -j$(nproc) ha_innodb
```

## Quick Sanity Check After Build

```bash
# Confirm the binary exists and reports correct version
./sql/mysqld --version

# Or if installed:
bin/mysqld --version
```

## Setting Up a Test Instance (without MTR)

```bash
mkdir -p /tmp/mysql_test_data

./bin/mysqld --initialize-insecure \
  --basedir=$(pwd) \
  --datadir=/tmp/mysql_test_data \
  --user=$(whoami)

./bin/mysqld_safe \
  --basedir=$(pwd) \
  --datadir=/tmp/mysql_test_data \
  --socket=/tmp/mysql_test.sock \
  --port=13306 &

sleep 3
./bin/mysql -S /tmp/mysql_test.sock -u root
```

## MTR Environment Setup

```bash
# Install perl dependencies for MTR
sudo apt-get install -y libdbi-perl libdbd-mysql-perl \
  libmysqlclient-dev perl-modules

# Or via cpan:
cpan install DBI DBD::mysql
```

## Common Build Failures

| Error | Fix |
|-------|-----|
| `Boost not found` | Set `-DWITH_BOOST=<path>` or `-DDOWNLOAD_BOOST=1` |
| `openssl/ssl.h not found` | `apt install libssl-dev` |
| `undefined reference to tirpc` | `apt install libtirpc-dev` |
| `protobuf version mismatch` | Build protobuf from source matching required version |
| `python3 not found` | `apt install python3-dev` |
| `CMAKE_BUILD_TYPE` warnings | Use exactly `Debug`, `Release`, or `RelWithDebInfo` |
| Linker OOM | Reduce parallelism: `make -j4` or add `-DCMAKE_EXE_LINKER_FLAGS="-Wl,--no-keep-memory"` |

## Percona-Specific Components

```bash
# Enable Percona features
-DWITH_ROCKSDB=1        # MyRocks storage engine
-DWITH_TOKUDB=0         # TokuDB (deprecated)
-DWITH_PAM=1            # PAM authentication
-DWITH_AUDIT_LOG=1      # Audit log plugin
```
