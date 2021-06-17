#!/bin/bash

update_gcc () {
  echo update-alternatives gcc-$1 priority=$2
  update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-$1 \
                    $2 \
                    --slave   /usr/bin/g++ g++ /usr/bin/g++-$1 \
                    --slave   /usr/bin/gcov gcov /usr/bin/gcov-$1 \
                    --slave   /usr/bin/gcov-dump gcov-dump /usr/bin/gcov-dump-$1 \
                    --slave   /usr/bin/gcov-tool gcov-tool /usr/bin/gcov-tool-$1 \
                    --slave   /usr/bin/gcc-ar gcc-ar /usr/bin/gcc-ar-$1 \
                    --slave   /usr/bin/gcc-nm gcc-nm /usr/bin/gcc-nm-$1 \
                    --slave   /usr/bin/gcc-ranlib gcc-ranlib /usr/bin/gcc-ranlib-$1

}

update_gcc 4.4  0
update_gcc 4.5 10
update_gcc 4.6 20
update_gcc 4.7 30
update_gcc 4.8 40
update_gcc 5   50
update_gcc 6   60
update_gcc 7   70
update_gcc 8   80
update_gcc 9   90

sudo update-alternatives --config gcc
