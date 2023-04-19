# in .bashrc set:
# source ~/sh/.bash_aliases
# source ~/sh/set_env.sh ~/sh

SH_PATH=$1

export PATH="$SH_PATH:$SH_PATH/sysbench.lua:$PATH"
export MTR_TERM="gnome-terminal --title %title% --wait --"
