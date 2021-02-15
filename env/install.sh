#! /bin/bash

#sudo yum install python38

repo=https://github.com/paulbeerkens/emonitor.git
version=master

#get source
#source scl_source enable rh-git218
rm -rf emonitor
git clone $repo

pushd emonitor > /dev/null
git checkout $version
popd > /dev/null

# Setup conda
if ! test -d $HOME/miniconda3; then
  wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  chmod +x Miniconda3-latest-Linux-x86_64.sh
  ./Miniconda3-latest-Linux-x86_64.sh -b
  rm -f Miniconda3-latest-Linux-x86_64.sh
fi

unset PYTHONPATH
source $HOME/miniconda3/etc/profile.d/conda.sh
conda env update -f /home/ec2-user/emonitor/env/conda.yml --prune -q
#$HOME/miniconda3/bin/conda env create --force -f /home/ec2-user/emonitor/env/conda.yml
conda activate emonitor
