# in .bashrc set:
# SH_DIR=~/sh
# source $SH_DIR/.bash_aliases
# source $SH_DIR/set_env.sh $SH_DIR

SH_PATH=$1

export PATH="$SH_PATH:$SH_PATH/sysbench.lua:$PATH"
export MTR_TERM="gnome-terminal --title %title% --wait --"
if [ -f /home/przemek/.ssh/llm.inc.sh ]; then
  source /home/przemek/.ssh/llm.inc.sh
fi
if [ -f /home/przemek/.ssh/mcp.inc.sh ]; then
  source /home/przemek/.ssh/mcp.inc.sh
fi
