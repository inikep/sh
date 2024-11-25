#!/bin/bash

update_clang_format () {
  echo update-alternatives clang-format-$1 priority=$2
  update-alternatives --install /usr/bin/clang-format clang-format /usr/bin/clang-format-$1 \
                    $2 \
                    --slave   /usr/bin/clang-format-diff clang-format-diff /usr/bin/clang-format-diff-$1

}

update_clang_format 4.0  40
update_clang_format 5.0  50
update_clang_format 6.0  60
update_clang_format 7    70
update_clang_format 8    80
update_clang_format 9    90
update_clang_format 10   100
update_clang_format 11   110
update_clang_format 12   120
update_clang_format 13   130
update_clang_format 14   140
update_clang_format 15   150

sudo update-alternatives --config clang-format
