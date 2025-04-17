#!/bin/bash

#SBATCH --account=def-siddiqi
#SBATCH --mail-user=megan.ng@mail.mcgill.ca
#SBATCH --mail-type=ALL

#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=6
#SBATCH --mem=15G
#SBATCH --time=1:00:00

# Declare model paths
modelPath="/home/meganng/projects/def-siddiqi/meganng/AstroSegmentationModel"                        # CHANGE TO YOUR OWN PATH
venvPath="/home/meganng/VirtualEnvironments/AstroSegmentationModel-py382-venv/bin/activate"     # CHANGE TO YOUR OWN PATH
mainPath="scripts/main.py"
configBasePath="configs/Astrocyte/base.yaml"
configFilePath="configs/Astrocyte/inference.yaml"
weightsPath="model_weights/grainy_astro_weights.pth.tar"                                        # CHANGE TO DESIRED WEIGHTS PATH

# activate environment
source $venvPath

# change directory to model package
cd $modelPath

# declare python path
export PYTHONPATH=$PYTHONPATH:$modelPath

# inference command specifications
CUDA_VISIBLE_DEVICES=0,1 python -u "$mainPath" --inference --config-base "$configBasePath" --config-file "$configFilePath" --checkpoint "$weightsPath"