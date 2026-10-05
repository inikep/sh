#!/bin/bash
# step.sh SHA12 : rebuild chain, auto-resolve that commit's conflicts, list what is left
cd /data/percona-server-linear
T=$1
rm -rf /data/ps-replay-vps-8.1.0-build/alf/chain
python3 /home/przemek/.claude/skills/ps-rename-or-plugin-to-component/scripts/backchain.py --x 4c08e7b0005a --map /data/ps-replay-vps-8.1.0-build/alf/map.py --touchers /data/ps-replay-vps-8.1.0-build/alf/touchers.txt --out /data/ps-replay-vps-8.1.0-build/alf/chain --resolutions /data/ps-replay-vps-8.1.0-build/alf/res --transform-files /data/ps-replay-vps-8.1.0-build/alf/test_ok.txt --transform-prog "python3 /data/ps-replay-vps-8.1.0-build/alf/test_transform.py {new}" --special /data/ps-replay-vps-8.1.0-build/alf/special.py --normalize "python3 /data/ps-replay-vps-8.1.0-build/alf/normalize.py {new}" | tail -1
[ -d /data/ps-replay-vps-8.1.0-build/alf/chain/conflicts/$T ] && python3 /home/przemek/.claude/skills/ps-rename-or-plugin-to-component/scripts/auto_resolve.py --conflicts /data/ps-replay-vps-8.1.0-build/alf/chain/conflicts/$T --out /data/ps-replay-vps-8.1.0-build/alf/res/$T --subs /data/ps-replay-vps-8.1.0-build/alf/subs.py --report /data/ps-replay-vps-8.1.0-build/alf/chain/manual-$T.txt
rm -rf /data/ps-replay-vps-8.1.0-build/alf/chain
python3 /home/przemek/.claude/skills/ps-rename-or-plugin-to-component/scripts/backchain.py --x 4c08e7b0005a --map /data/ps-replay-vps-8.1.0-build/alf/map.py --touchers /data/ps-replay-vps-8.1.0-build/alf/touchers.txt --out /data/ps-replay-vps-8.1.0-build/alf/chain --resolutions /data/ps-replay-vps-8.1.0-build/alf/res --transform-files /data/ps-replay-vps-8.1.0-build/alf/test_ok.txt --transform-prog "python3 /data/ps-replay-vps-8.1.0-build/alf/test_transform.py {new}" --special /data/ps-replay-vps-8.1.0-build/alf/special.py --normalize "python3 /data/ps-replay-vps-8.1.0-build/alf/normalize.py {new}" | tail -1
grep "^$T" /data/ps-replay-vps-8.1.0-build/alf/chain/conflicts.txt | cut -f2,3
