git diff -U0 --no-color HEAD^1 *.c *.cc *.cpp *.h *.hpp *.i *.ic *.ih | clang-format-diff.py -binary=clang-format-5.0 -style=file -p1
