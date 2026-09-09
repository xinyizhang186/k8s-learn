# 要删除的分支名
git init
git remote add origin https://github.com/xinyizhang186/k8s-learn.git
git push origin --delete recurit --force

git init
git status
# 创建并切换到 dev 分支
git checkout -b Me-all
git add --all
git status

git commit -m "Me-all"
git remote add origin https://github.com/xinyizhang186/k8s-learn.git
git remote set-url origin https://github.com/xinyizhang186/k8s-learn.git




# gitcode
git init
git remote add origin https://gitcode.com/2401_87127444/AutoK8s.git
git add .
git commit -m "Initial commit"
git branch -m main

git remote set-url origin git@gitcode.com:2401_87127444/AutoK8s.git
git push -u origin main