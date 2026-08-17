#!/bin/bash

SECONDS=0

usage() {
	echo "Usage: $0 <java|python|rust|csharp>" >&2
}

case "${1,,}" in
	java)
		LANGUAGE="java"
		;;
	python|py)
		LANGUAGE="python"
		;;
	rust|rs)
		LANGUAGE="rust"
		;;
	csharp|c#|cs|chsarp)
		LANGUAGE="csharp"
		;;
	-h|--help)
		usage
		exit 0
		;;
	"")
		usage
		exit 2
		;;
	*)
		echo "Unsupported language: $1" >&2
		usage
		exit 2
		;;
esac

LANGUAGE_CONFIG="${LANGUAGE}_dataset_config.json"

if [[ ! -f "drivers/CASCADE/$LANGUAGE_CONFIG" ]]; then
	echo "Missing CASCADE config: drivers/CASCADE/$LANGUAGE_CONFIG" >&2
	exit 2
fi

echo "Selected language: $LANGUAGE"

unzip -o dataset.zip

if [[ ! -d "$LANGUAGE" ]] || [[ -z $(find "$LANGUAGE" -type f -name analyzed.json -print -quit) ]]; then
	echo "dataset.zip contains no analyzed.json cases for $LANGUAGE" >&2
	exit 2
fi

WORKING_DIR=$(pwd)
CASCADE_BIN=${CASCADE_BIN:-"$WORKING_DIR/../../cascade.venv/bin/CASCADE"}
export CASCADE_BIN

#DRIVERS_LIST=()
#DRIVERS_LIST=("DocChecker" "Baseline" "C4RLLaMA")
DRIVERS_LIST=("CASCADE")

#  alter the drivers list to run the specific drivers you want, if the list is empty, it will run all the drivers in the drivers folder

(
cd "$LANGUAGE"
for repo in */*
do
(
	echo "At repository: $repo ---------------------"
	cd "$repo"
	# clone this repo 
	git clone https://github.com/$repo ./repository
	
	for commit in *
	do
	
		if [ $commit == "repository" ]
		then continue
		fi

	(
		echo "    At commit: $commit -------"
		
		# checkout specific commit and initialize the submodules belonging to it.
		if ! (
			cd repository
			git checkout --force "$commit"

			if [[ -f .gitmodules ]]; then
				git submodule sync --recursive
				git submodule update --init --recursive
			fi
		); then
			echo "Could not prepare commit $commit" >&2
			exit 1
		fi
		cd "$commit"
		cp -r "../repository" "./backup"

		# Copy a commit-specific container setup script when provided.
		if [[ -f "./container_patch.sh" ]]; then
			cp "./container_patch.sh" "./backup/.cascade-container-patch.sh"
		fi
		
		# Apply a case-specific build patch when the dataset provides one.
		if [[ -f "./file.patch" ]]; then
			(cd "./backup"; patch -p1 -f < ../file.patch)
		fi

		for num in *
		do
			if [[ $num == "backup" ||
				  $num == "file.patch" ||
				  $num == "container_patch.sh" ]]
			then continue
			fi
		(	
			echo "        At number: $num"
			
			cd $WORKING_DIR/drivers
			if [ ${#DRIVERS_LIST[@]} -eq 0 ]; then
				drivers_to_run=(*)
		  	else
				drivers_to_run=("${DRIVERS_LIST[@]}")
			fi
			
			for driver in "${drivers_to_run[@]}";
			do
			(
				echo "copy $driver"
				
				# copy required stuff and execute
				cp -r $driver "../$LANGUAGE/$repo/$commit/$num/$driver"
				cd "../$LANGUAGE/$repo/$commit"
				cp -r "./backup" "./$num/$driver/repository"
				cd "./$num"
				cp "./analyzed.json" "./$driver/analyzed.json"
				cd "./$driver"

				bash driver.sh "$LANGUAGE"

				mv "result.txt" "../result_$driver.txt"
				mv "log.txt" "../log_$driver.txt"
				mv "errors.txt" "../errors_$driver.txt"	

				cp "analyzed.json" "../analyzed.json"
				#  -----------

				cd ..
				rm -rf $driver
			)
			done
		)		
		done
		# echo Press to continue
		# read  
		rm -rf ./backup		
	)				
	done
	rm -rf ./repository
)
done
{
	git -C "$WORKING_DIR/.." rev-parse HEAD
	date
	echo
} >> "$WORKING_DIR/runs"
)

printf 'Finished in %d h %02d m %02d s\n' $((SECONDS/3600)) $(((SECONDS/60)%60)) $((SECONDS%60))
