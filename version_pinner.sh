#!/bin/sh
if [ ! -f requirements.txt ]; then
  echo "No requirements.txt file found. Are you in the correct path? If yes, create an initial requirements.txt file."
fi
if [ ! -f setup.py ]; then
  echo "No setup.py file found. Are you in the correct path?"
fi
echo "Creating backups of setup files"
cp requirements.txt requirements_old.txt
cp setup.py setup_old.py
echo "Patching setup.py to install the latest version of all packages"
sed -E -i "s/('.*)==.*'/\1'/" setup.py
echo "Running setup.sh to update all packages to the latest versions..."
./setup.sh > /dev/null 2>&1
echo "...done"
echo "Generating an updated requirements.txt file"
env/bin/python -m pip freeze > requirements.txt
sed -E -i "s/main @ .*//" requirements.txt
sed -i '/^\s*$/d' requirements.txt
new_content=$(sed "s/.*/'&',/" requirements.txt | sed "s/''/',/")
new_content_escaped=$(printf '%s\n' "$new_content" | perl -pe "s/'/\\\'/g; s/\", '/\', '/g; s/', \"/\', \'/g; s/^'//g; s/'$//g;")
source_contents=$(perl -0777 -pe "s/install_requires\=[^\]]+\]/install_requires\=[$new_content_escaped]/s" setup.py)
echo "$source_contents" > setup.py
autopep8 --in-place --aggressive --aggressive setup.py
diff_packages=$(diff -y --suppress-common-lines requirements_old.txt requirements.txt)
if [ -n "$diff_packages" ]; then
  echo "The following packages have been updated:"
  echo "$diff_packages"
fi