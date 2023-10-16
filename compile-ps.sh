#!/bin/bash

#set -o errexit
#set -o xtrace

# PATH=/github/sh:/home/inikep/bin:/home/inikep/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin
# PATH=/github/sh:/usr/lib/ccache:/home/inikep/bin:/home/inikep/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin

# SRV_VER=$(echo ${1//[^0-9.]/ })
# SRV_VER=${1:(-3)}

case $1 in
  "") SRV_VER="unknown" ;;
  wdc-*) SRV_VER="WDC8" ;;
  FB56-*) SRV_VER="FB56" ;;
  fb-prod*) SRV_VER="FB56" ;;
  fb-5.*) SRV_VER="FB56" ;;
  FB8-*) SRV_VER="FB8" ;;
  fb-8.*) SRV_VER="FB8" ;;
  mysql-5.7*) SRV_VER="MS57" ;;
  mysql-8.*) SRV_VER="MS8" ;;
  *5.6*) SRV_VER="5.6" ;;
  *5.7*) SRV_VER="5.7" ;;
  *8.0*) SRV_VER="8.0" ;;
  *) SRV_VER="8.0" ;;
esac


if [[ "$SRV_VER" != +(5.6|5.7|8.0|WDC8) ]] && [[ "$SRV_VER" != +(FB56|FB8) ]] && [[ "$SRV_VER" != +(MS57|MS8) ]]; then
   echo Unknown SRV_VER=$SRV_VER;
   echo "Usage: compile-ps.sh <server_dir> <debug/rel/asan/valgrind/rocksdb/tokudb/additional_options>";
   echo "  e.g. compile-ps.sh mysql-8.0 rel";
   echo "  or   compile-ps.sh percona-5.7 asan";
   echo "       compile-ps.sh 5.7";
   echo "       compile-ps.sh 8.0 valgrind";
   echo "       compile-ps.sh fb-5.6.35 rocksdb -DMYSQL_MAINTAINER_MODE=0 -DENABLED_LOCAL_INFILE=1 -DENABLE_DTRACE=0";
   echo "       compile-ps.sh fb-8.0 clang8";
   echo "       compile-ps.sh percona-5.7 gcc9";
   echo "       export LD_LIBRARY_PATH=/usr/local/lib/; compile-ps.sh FB8-153 -DCMAKE_CXX_FLAGS=-DHAVE_JEMALLOC=1 -DCMAKE_CXX_LINK_FLAGS=\\\"-L/usr/local/lib/ -ljemalloc\\\"";
   exit 1
fi

DEBUG=1;
for var in "${@:2}"
do
case $var in
  debug) DEBUG=1; RELEASE=0 ;;
  rel) DEBUG=0; RELEASE=1 ;;
  docker) DOCKER=1 ;;
esac
done

SRV_ROOT=${SRV_ROOT:-/data/mysql-server}
SRV_PATH=$SRV_ROOT/$1

OS_VERSION=$(lsb_release -d -s)
if [[ "${OS_VERSION}" = *"CentOS release 6."* ]] || [[ "${OS_VERSION}" = *"CentOS Linux release 7."* ]]; then
   BUILD_PATH=/data/ps-build-bin/centos7-$1
   JOB_CMAKE='cmake3'
else
   BUILD_PATH=$SRV_PATH
#   JOB_CMAKE='cmake --trace-source=/data/mysql-server/fb-8.0.28/storage/rocksdb/CMakeLists.txt'
   JOB_CMAKE='cmake'
fi

if [ "$DOCKER" != "1" ]; then
   BUILD_PATH=$SRV_PATH
else
   VERSION_CODENAME=`grep '^VERSION_CODENAME' /etc/os-release | cut -d "=" -f 2`
   ARCH=`uname -m`
   BUILD_PATH=/data/docker/${VERSION_CODENAME}-$ARCH-$1
fi

if [ "$RELEASE" == "1" ]; then
   BUILD=RelWithDebInfo;
   BUILD_PATH+=-rel;
else
   BUILD=Debug;
   BUILD_PATH+=-deb;
fi

STOP_ON_WARN=ON;
for var in "${@:2}"
do
case $var in
  deb*) ;;
  rel) ;;
  docker) ;;
  zenfs*) ZENFS=1; BUILD_PATH+=-zenfs ;;
  invert*) INVERTED=1; BUILD_PATH+=-inverted ;;
  bundle*) BUNDLED=1; BUILD_PATH+=-bundled ;;
  jenkins) JENKINS=1; BUILD_PATH+=-jenkins ;;
  jemalloc) JEMALLOC=1; BUILD_PATH+=-jemalloc ;;
  boring*) BORINGSSL=$var; BUILD_PATH+=-$var ;;
  asan) ASAN=1; BUILD_PATH+=-asan ;;
  msan) MSAN=1; BUILD_PATH+=-msan ;;
  valgrind) VALGRIND=1; BUILD_PATH+=-valgrind ;;
  rocks*) ROCKSDB=1; BUILD_PATH+=-rocks ;;
  toku*) TOKUDB=1; BUILD_PATH+=-toku ;;
  clang*) CLANG=1; CC=clang-${var:5:6}; CXX=clang++-${var:5:6}; BUILD_PATH+=-$var ;;
  gcc*) CC=gcc-${var:3:4}; CXX=g++-${var:3:4}; BUILD_PATH+=-$var ;;
  noerr) STOP_ON_WARN=OFF; BUILD_PATH+=-noerr ;;
  g1) OPT_G1=1; BUILD_PATH+=-g1 ;;

  *) ADDITIONAL_OPTS+="$var " ;;
esac
done

if [ "$ADDITIONAL_OPTS" != "" ]; then BUILD_PATH+=-add; fi

if [[ "${OS_VERSION}" = *"CentOS release 6."* ]] || [[ "${OS_VERSION}" = *"CentOS Linux release 7."* ]]; then
   ADDITIONAL_OPTS+="-DWITH_PROTOBUF=bundled -DWITH_MECAB= -DWITH_LIBEVENT=bundled -DWITH_EDITLINE=bundled -DWITH_ICU=bundled"
fi

if [ "$CC" == "clang-4" ] || [ "$CC" == "clang-5" ] || [ "$CC" == "clang-6" ]; then
   CC=$CC.0; CXX=$CXX.0;
fi

if [ "$CC" == "gcc-4" ]; then
   CC=$CC.8; CXX=$CXX.8;
fi

if [[ "${CC}x" == "x" ]]; then echo "need compiler e.g. gcc12 or clang14"; exit 1; fi

echo CC=$CC CXX=$CXX SRV_VER=$SRV_VER DEBUG=$DEBUG RELEASE=$RELEASE ASAN=$ASAN MSAN=$MSAN VALGRIND=$VALGRIND ROCKSDB=$ROCKSDB TOKUDB=$TOKUDB JENKINS=$JENKINS JEMALLOC=$JEMALLOC BORINGSSL=$BORINGSSL
echo BUILD_PATH=$BUILD_PATH
echo ADDITIONAL_OPTS="'$ADDITIONAL_OPTS'"

CMAKE_OPT_COMMON="
 -DCMAKE_BUILD_TYPE=$BUILD
 -DMYSQL_MAINTAINER_MODE=$STOP_ON_WARN
 -DCMAKE_C_COMPILER=$CC
 -DCMAKE_CXX_COMPILER=$CXX
 -DCMAKE_C_COMPILER_LAUNCHER=ccache
 -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
 -DBUILD_CONFIG=mysql_release
 -DDOWNLOAD_BOOST=1
 -DWITH_BOOST=../_deps
";

CMAKE_MYSQL_57="
 $CMAKE_OPT_COMMON
 -DWITH_PACKAGE_FLAGS=OFF
 -DFEATURE_SET=community
 -DENABLE_DTRACE=OFF
 -DWITH_ZLIB=bundled
";

CMAKE_PERCONA_57="
 $CMAKE_MYSQL_57
 -DWITH_KEYRING_VAULT=ON
 -DWITH_NUMA=ON
 -DWITH_PAM=OFF
 -DWITH_MECAB=system
";


CMAKE_MYSQL_80="
 $CMAKE_OPT_COMMON
 -DWITH_PACKAGE_FLAGS=OFF
 -DWITH_NDB=OFF
 -DWITH_NDBCLUSTER=OFF
 -DWITH_MECAB=system
 -DWITH_NUMA=ON
 -DWITH_SYSTEM_LIBS=ON
 -DWITH_EDITLINE=system
";
# -DWITH_ZLIB=system       # ZLIB version must be at least 1.2.12, found 1.2.11.
# -DWITH_RAPIDJSON=system  # System rapidjson lacks some fixes required for support of regular

CMAKE_PERCONA_LIBS_80="
 -DWITH_COREDUMPER=ON
 -DWITH_PAM=ON
 -DWITH_KEYRING_VAULT=ON
 -DWITH_KEYRING_VAULT_TEST=ON
 -DWITH_PERCONA_AUTHENTICATION_LDAP=ON
";

CMAKE_PERCONA_80="
 $CMAKE_MYSQL_80
 $CMAKE_PERCONA_LIBS_80
";

CMAKE_PERCONA_80_BUNDLED="
 $CMAKE_OPT_COMMON
 -DWITH_AUTHENTICATION_CLIENT_PLUGINS=ON
 -DWITH_AUTHENTICATION_FIDO=ON
 -DWITH_AUTHENTICATION_KERBEROS=ON
 -DWITH_AUTHENTICATION_LDAP=ON

 -DWITH_NDB=ON
 -DWITH_NDBCLUSTER=ON
 -DWITH_NDB_JAVA=OFF

 -DWITH_ROUTER=OFF
 -DWITH_UNIT_TESTS=OFF
 -DWITH_NUMA=OFF

 -DWITH_EDITLINE=bundled
 -DWITH_FIDO=bundled
 -DWITH_ICU=bundled
 -DWITH_LIBEVENT=bundled
 -DWITH_LZ4=bundled
 -DWITH_PROTOBUF=bundled
 -DWITH_RAPIDJSON=bundled
 -DWITH_ZLIB=bundled
 -DWITH_ZSTD=bundled

 -DWITH_ARCHIVE_STORAGE_ENGINE=OFF
 -DWITH_BLACKHOLE_STORAGE_ENGINE=OFF
 -DWITH_EXAMPLE_STORAGE_ENGINE=ON
 -DWITH_FEDERATED_STORAGE_ENGINE=OFF
 -DWITHOUT_PERFSCHEMA_STORAGE_ENGINE=ON
 -DWITH_INNODB_MEMCACHED=ON
";

# -DWITH_PACKAGE_FLAGS=OFF  The default is ON for nondebug builds.
# -DREPRODUCIBLE_BUILD=OFF  defaults to ON for RelWithDebInfo builds

# MySQL 8.0.31 defaults
# WITH_LDAP=system|path
# WITH_SASL=system|path
# WITH_SSL=system|path
#
# WITH_NDB=OFF
# WITH_NDBCLUSTER=OFF
# WITH_NDB_JAVA=ON
# WITH_ROUTER=ON
# WITH_UNIT_TESTS=ON
#
# WITH_CURL --- disabled|system
# WITH_MECAB --- disabled|system
# WITH_NUMA --- autodetect|ON|OFF
#
# WITH_EDITLINE=bundled
# WITH_FIDO=bundled
# WITH_ICU=bundled
# WITH_LIBEVENT=bundled
# WITH_LZ4=bundled
# WITH_PROTOBUF=bundled
# WITH_RAPIDJSON=bundled
# WITH_ZLIB=bundled
# WITH_ZSTD=bundled
#
# WITH_SYSTEM_LIBS = CURL ICU LIBEVENT LZ4 PROTOBUF SSL ZSTD FIDO




# -DWITH_READLINE=system  
# -DMERGE_UNITTESTS=ON
# -DWITH_UNIT_TESTS=OFF

CMAKE_BUNDLED_57="
 $CMAKE_MYSQL_57
 -DENABLE_DOWNLOADS=1
 -DDOWNLOAD_BOOST=1
 -DWITH_BOOST=../_deps
 -DWITH_KEYRING_VAULT=ON

 -DWITH_NUMA=OFF
 -DWITH_EMBEDDED_SERVER=OFF
 -DWITH_EDITLINE=bundled
 -DWITH_LIBEVENT=system
 -DWITH_LZ4=system
 -DWITH_ZSTD=bundled
 -DWITH_PROTOBUF=system
 -DWITH_SSL=system
 -DWITH_ZLIB=bundled
 -DWITH_ARCHIVE_STORAGE_ENGINE=OFF
 -DWITH_BLACKHOLE_STORAGE_ENGINE=OFF
 -DWITH_EXAMPLE_STORAGE_ENGINE=ON
 -DWITH_FEDERATED_STORAGE_ENGINE=OFF
 -DWITH_QUERY_RESPONSE_TIME=ON
 -DWITHOUT_PARTITION_STORAGE_ENGINE=ON
 -DWITHOUT_PERFSCHEMA_STORAGE_ENGINE=ON
 -DWITH_SCALABILITY_METRICS=ON
 -DWITH_INNODB_MEMCACHED=ON
 -DWITH_MECAB=system
";

OPTIONS_INVERTED="-DWITH_NDB=ON -DWITH_NDBCLUSTER=ON -DWITH_NDB_JAVA=OFF -DWITH_ROUTER=OFF -DWITH_UNIT_TESTS=OFF -DWITH_NUMA=OFF"
OPTIONS_SE_INVERTED="-DWITH_ARCHIVE_STORAGE_ENGINE=OFF -DWITH_BLACKHOLE_STORAGE_ENGINE=OFF -DWITH_EXAMPLE_STORAGE_ENGINE=ON -DWITH_FEDERATED_STORAGE_ENGINE=OFF -DWITHOUT_PERFSCHEMA_STORAGE_ENGINE=ON -DWITH_INNODB_MEMCACHED=ON"

CMAKE_WDC_80="
 $CMAKE_MYSQL_80
 -DWITH_SYSTEM_LIBS=ON
 -DWITH_NUMA=ON
 -DROCKSDB_PLUGINS=zenfs
 -DWITH_ZENFS_UTILITY=ON
";

CMAKE_FACEBOOK_56="
 $CMAKE_MYSQL_56
 -DWITH_LZ4=system
 -DWITH_ZSTD=system
 -DMYSQL_GITHASH=mysqlHash -DMYSQL_GITDATE=mysqlDate
 -DROCKSDB_GITHASH=rocksdbHash -DROCKSDB_GITDATE=rocksdbDate
 -DWITH_PERFSCHEMA_STORAGE_ENGINE=1
";

CMAKE_FACEBOOK_80="
 $CMAKE_MYSQL_80
 -DWITH_LZ4=bundled
 -DWITH_ZSTD=bundled
 -DMYSQL_GITHASH=mysqlHash -DMYSQL_GITDATE=mysqlDate
 -DROCKSDB_GITHASH=rocksdbHash -DROCKSDB_GITDATE=rocksdbDate
 -DENABLE_EXPERIMENT_SYSVARS=1
";


CMAKE_JENKINS_80="$CMAKE_UPSTREAM_80 -DWITH_MECAB= -DWITH_SYSTEM_LIBS=ON -DWITH_PROTOBUF=bundled -DWITH_ICU=bundled
                  -DWITH_EDITLINE=bundled -DWITH_NUMA=ON -DWITH_INNODB_MEMCACHED=ON '-DCOMPILATION_COMMENT=Percona Server (GPL), Release , Revision XXXXXX-debug'
                  -DMYSQL_MAINTAINER_MODE=OFF -DBUILD_TESTING=OFF";

case $SRV_VER in
     5.7)
         if [ "$BUNDLED" == "1" ]; then
           CMAKE_OPT="$CMAKE_BUNDLED_57";
         else
           CMAKE_OPT="$CMAKE_PERCONA_57";
         fi
         ;;
     FB56)
          CMAKE_OPT="$CMAKE_FACEBOOK_56";
          ;;
     FB8)
          CMAKE_OPT="$CMAKE_FACEBOOK_80";
          ;;
     WDC8)
          CMAKE_OPT="$CMAKE_WDC_80";
          ;;
     MS57)
          CMAKE_OPT="$CMAKE_MYSQL_57";
          ;;
     MS8)
          CMAKE_OPT="$CMAKE_MYSQL_80";
          ;;
       *)
         if [ "$BUNDLED" == "1" ]; then
           CMAKE_OPT="$CMAKE_PERCONA_80_BUNDLED";
         else
           CMAKE_OPT="$CMAKE_PERCONA_80";
         fi
         ;;
esac


if [ "$OPT_G1" == "1" ]; then
   COMPILE_OPT+=(
        -DCMAKE_C_FLAGS_DEBUG=-g1
        -DCMAKE_CXX_FLAGS_DEBUG=-g1
        '-DCMAKE_C_FLAGS_RELWITHDEBINFO=-O2 -g1 -DNDEBUG'
        '-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O2 -g1 -DNDEBUG'
   )
fi

if [ "$CC" == "clang-4.0" ] || [ "$CC" == "clang-5.0" ]; then
      COMPILE_OPT+=(
       '-DCMAKE_C_FLAGS=-isystem /usr/include/c++/9 -isystem /usr/include'
       '-DCMAKE_CXX_FLAGS=-isystem /usr/include/c++/9 -isystem /usr/include'
      )
fi

if [ "$ROCKSDB" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT -DWITH_ROCKSDB=ON";
fi

if [ "$ZENFS" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT -DROCKSDB_PLUGINS=zenfs -DWITH_ZENFS_UTILITY=ON";
fi

if [ "$TOKUDB" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT -DWITH_TOKUDB=ON";
fi

if [ "$ASAN" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT -DWITH_ASAN=ON -DWITH_ASAN_SCOPE=ON";
fi
# -DWITH_UBSAN=ON

if [ "$MSAN" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT -DWITH_MSAN=ON";
fi

if [ "$VALGRIND" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT -DWITH_VALGRIND=ON";
fi

if [ "$JENKINS" == "1" ]; then
   CMAKE_OPT="$CMAKE_JENKINS_80";
fi

if [ "$JEMALLOC" == "1" ]; then
#   CMAKE_OPT="$CMAKE_OPT -DHAVE_JEMALLOC=1 -DCMAKE_CXX_LINK_FLAGS=\"-L/usr/local/lib/ -ljemalloc\" ";
   CMAKE_OPT="$CMAKE_OPT -DWITH_JEMALLOC=1";
fi

if [ "$BORINGSSL" != "" ]; then
   CMAKE_OPT="$CMAKE_OPT -DWITH_SSL=system -DCMAKE_PREFIX_PATH=/data/lib/$BORINGSSL";
fi

if [ "$INVERTED" == "1" ]; then
   CMAKE_OPT="$CMAKE_OPT $OPTIONS_INVERTED $OPTIONS_SE_INVERTED";
fi

mkdir $BUILD_PATH;
cd $BUILD_PATH && rm -rf * &&
   echo CMAKE_OPT=${CMAKE_OPT} &&
   echo COMPILE_OPT=\"${COMPILE_OPT[@]}\" &&
   echo ADDITIONAL_OPTS="$ADDITIONAL_OPTS" &&
   $JOB_CMAKE ${CMAKE_OPT} "${COMPILE_OPT[@]}" $ADDITIONAL_OPTS $SRV_PATH &&
   echo CMAKE_OPT=${CMAKE_OPT} &&
   echo COMPILE_OPT=\"${COMPILE_OPT[@]}\" &&
   echo ADDITIONAL_OPTS="$ADDITIONAL_OPTS"
exit

