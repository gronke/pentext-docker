#!/bin/sh
set -e

cd "$CI_PROJECT_DIR"
TARGET_DIR="target"
PROJECT_NAME="$(echo ${CI_PROJECT_NAME} | sed s/^off-// | sed s/^pen-//)"

set -x
mkdir -p $TARGET_DIR

to_csv()
{
	DOC_TYPE="${1:-report}"
	echo "Building ${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.csv"
	java -jar /saxon.jar \
		"-s:source/${DOC_TYPE}.xml" \
		"-xsl:xslt/findings2csv.xsl" \
		"-o:${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.csv" \
		-xi
}

to_fo()
{
	DOC_TYPE="${1:-report}"
	echo "Building ${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.fo"
	java -jar /saxon.jar \
		"-s:source/${DOC_TYPE}.xml" \
		"-xsl:xslt/generate_${DOC_TYPE}.xsl" \
		"-o:${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.fo" \
		-xi
}

to_pdf()
{
	DOC_TYPE="${1:-report}"
	to_fo "$DOC_TYPE"
	echo "Building ${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.pdf"
	/fop/fop \
		-c /fop/conf/rosfop.xconf \
		"${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.fo" \
		"${TARGET_DIR}/${DOC_TYPE}_${PROJECT_NAME}.pdf" \
		-v \
		-noassembledoc \
		-noedit \
		-o "$PDF_PASSWORD" \
		-u "$PDF_PASSWORD" 
}

if [ -f "source/report.xml" ]; then
	to_pdf report
	to_csv report
fi
if [ -f "source/offerte.xml" ]; then
	to_pdf offerte
fi
if [ -f "source/document.xml" ]; then
	to_pdf document
fi

ls -al $TARGET_DIR
