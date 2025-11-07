hhdrel ()
{
  # Check we have at least two parameters
  if [ $# -lt 1 ]
  then
    echo "Usage: hhdrel <version>"
    return
  fi

  relver=$1
  tag=v$1
  
  if [ ! -f './hhd.spec' ]; then
    echo "No hhd.spec found. Wrong dir"
    return
  fi

(
  set -e
  # Update translations
  pybabel extract --no-location -F i18n/babel.cfg -o i18n/hhd.tmp.pot src/hhd
  pybabel extract --no-location -F i18n/babel.cfg -o i18n/adjustor.tmp.pot src/adjustor
  msgmerge --update --backup=none i18n/hhd.pot i18n/hhd.tmp.pot
  msgmerge --update --backup=none i18n/adjustor.pot i18n/adjustor.tmp.pot
  rm i18n/*.tmp.pot
  
  # for lang in $(ls i18n | grep -Eo '^.+_.+$'); do
  #   pybabel update -D hhd -i i18n/hhd.pot -d i18n -l $lang
  #   pybabel update -D adjustor -i i18n/adjustor.pot -d i18n -l $lang
  # done
  sed -i "s/version = \".*\"/version = \"$relver\"/" pyproject.toml
  sed -i "s/^Version: *.*/Version:        $relver/" hhd.spec
  pybabel compile -D hhd -d ./i18n
  pybabel compile -D adjustor -d ./i18n
  # find i18n -type f -name "*.po*" -exec sed -i 's/^"POT-Creation-Date: .*"/"POT-Creation-Date: 2020-01-01 00:00+0000\\n"/' {} +
  git add pyproject.toml i18n/*
  git commit -m "bump to $relver"
  git tag -f $tag && git push origin $tag -f
) &&
  xdg-open "https://github.com/hhd-dev/hhd/releases/new?tag=$tag"
}