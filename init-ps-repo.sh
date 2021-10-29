mkdir mysql-server/git
cd mysql-server
git clone https://github.com/inikep/percona-server.git
cd percona-server
git init --separate-git-dir=../.git

git remote add mysql https://github.com/mysql/mysql-server.git
git fetch mysql
git worktree add -b mysql-5.6.35 ../mysql-5.6.35 mysql-5.6.35
git worktree add -b mysql-5.7 ../mysql-5.7 mysql/5.7
git worktree add -b mysql-8.0 ../mysql-8.0 mysql/8.0
git worktree add -b mysql-8.0.13 ../mysql-8.0.13 tags/mysql-8.0.13

git remote add facebook https://github.com/facebook/mysql-5.6.git
git fetch facebook
git worktree add -b fb-5.6.35 ../fb-5.6.35 facebook/fb-mysql-5.6.35
git worktree add -b fb-8.0.13 ../fb-8.0.13 facebook/fb-mysql-8.0.13

git remote add inikep-fb https://github.com/inikep/mysql-5.6.git

git remote add percona https://github.com/percona/percona-server.git
git fetch percona
git worktree add -b percona-5.5 ../percona-5.5 percona/5.5
git worktree add -b percona-5.6 ../percona-5.6 percona/5.6
git worktree add -b percona-5.7 ../percona-5.7 percona/5.7
git worktree add -b percona-8.0 ../percona-8.0 percona/8.0
git worktree add ../5.5 percona/5.5
git worktree add ../5.6 percona/5.6
git worktree add ../5.7 percona/5.7
git worktree add ../8.0 percona/8.0
