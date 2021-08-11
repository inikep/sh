SH_PATH=$1

if [ -f $SH_PATH/.bash_aliases ]; then
    . $SH_PATH/.bash_aliases
fi

export PATH="$SH_PATH:$SH_PATH/sysbench.lua:$PATH"
export MTR_TERM="gnome-terminal --title %title% --wait -x"
