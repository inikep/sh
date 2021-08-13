# in .bashrc set:
# source /data/sh/.bash_aliases
# source /data/sh/set_env.sh /data/sh

SH_PATH=$1

export PATH="$SH_PATH:$SH_PATH/sysbench.lua:$PATH"
export MTR_TERM="gnome-terminal --title %title% --wait -x"
