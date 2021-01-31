#!/bin/sh
cd "$CI_PROJECT_DIR"
TARGET_DIR="target"

mkdir -p $TARGET_DIR

to_fo()
{
	DOC_TYPE="${1:-report}"
	echo "Building ${TARGET_DIR}/${DOC_TYPE}_${CI_PROJECT_NAME}.fo"
	java -jar /saxon.jar \
		"-s:source/${DOC_TYPE}.xml" \
		"-xsl:xslt/generate_${DOC_TYPE}.xsl" \
		"-o:${TARGET_DIR}/${DOC_TYPE}_${CI_PROJECT_NAME}.fo" \
		-xi
}

to_pdf()
{
	DOC_TYPE="${1:-report}"
	to_fo "$DOC_TYPE"
	echo "Building ${TARGET_DIR}/${DOC_TYPE}_${CI_PROJECT_NAME}.pdf"
	/fop/fop \
		-c /fop/conf/rosfop.xconf \
		"${TARGET_DIR}/${DOC_TYPE}_${CI_PROJECT_NAME}.fo" \
		"${TARGET_DIR}/${DOC_TYPE}_${CI_PROJECT_NAME}.pdf" \
		-v \
		-nocopy \
		-noaccesscontent \
		-noassembledoc \
		-noedit \
		-noannotations \
		-o "$PDF_PASSWORD" \
		-u "$PDF_PASSWORD" 
}

if [ -f "source/report.xml" ]; then
	to_pdf report
elif [ -f "source/offerte.xml" ]; then
	to_pdf offerte
fi

ls -al $TARGET_DIR
