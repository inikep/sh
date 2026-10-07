git diff -U0 --no-color HEAD^1 *.c *.cc *.cpp *.h *.hpp *.i *.ic *.ih | clang-format-diff -style=file -p1
