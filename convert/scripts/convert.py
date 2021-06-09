#!/usr/local/env python3
import typing
import re
import os
import os.path
import pathlib
import xml.dom.minidom
import urllib.request

import pypandoc
from gitlab import Gitlab
from slugify import slugify

SKIP_EXISTING=(str(os.environ.get("SKIP_EXISTING", "1")) == "1")
GITLAB_TOKEN=os.environ["PROJECT_ACCESS_TOKEN"]
GITLAB_SERVER_URL = os.environ.get(
	"CI_SERVER_URL",
	"https://git.radicallyopensecurtity.com"
)

gitlab = Gitlab(
  GITLAB_SERVER_URL,
  private_token=GITLAB_TOKEN
)
gitlab.auth()

opener = urllib.request.build_opener()
opener.addheaders = [('PRIVATE-TOKEN', GITLAB_TOKEN)]
urllib.request.install_opener(opener)

pathlib.Path("uploads").mkdir(parents=True, exist_ok=True)
pathlib.Path("findings").mkdir(parents=True, exist_ok=True)
pathlib.Path("non-findings").mkdir(parents=True, exist_ok=True)


class InvalidUploadPathException(Exception):
	pass


upload_path_pattern = re.compile(
	"(?:\.{2})?/uploads/(?P<hex>[A-Fa-f0-9]{32})/(?P<filename>[^\.][^/]+)"
)


class Upload:

	def __init__(self, path) -> None:
		self.path = path

	@property
	def path(self):
		return f"/uploads/{self.hex}/{self.filename}"
	
	@path.setter
	def path(self, value):
		match = upload_path_pattern.match(value)
		if match is None:
			raise InvalidUploadPathException()
		self.hex = match["hex"]
		self.filename = match["filename"]

	@property
	def url(self):
		project_url = os.environ["CI_PROJECT_URL"]
		return f"{project_url}{self.path}"
	
	@property
	def local_path(self):
		return f"uploads/{self.hex}/{self.filename}"

	def download(self) -> None:
		if os.path.exists(self.local_path) is True:
			print(f"skip download {self.local_path} - file exists")
			return
		dirname = os.path.dirname(self.local_path)
		os.makedirs(dirname, exist_ok=True)
		print(f"downloading {self.url} to {self.local_path}")
		urllib.request.urlretrieve(self.url, self.local_path)


class ReportAsset:

	def __init__(
		self,
		id: int,
		iid: int,
		title: str,
		project=None
	):

		if type(id) != int:
			raise Exception("ID must be an Integer")

		if type(iid) != int:
			raise Exception("Issue ID must be an Integer")

		self.id = id
		self.iid = iid
		self.title = title
		self.project = project

	@property
	def doc(self):
		raise NotImplementedError()

	@property
	def processed_doc(self):
		doc = self.doc
		images = doc.getElementsByTagName("img")
		image_urls = [image.getAttribute("src") for image in images]
		for image in images:
			image_url = image.getAttribute("src");
			try:
				attachment = Upload(image_url)
				attachment.download()
				image.setAttribute("src", f"../{attachment.local_path}")
			except InvalidUploadPathException:
				pass
		return doc

	@property
	def prettyxml(self):
		return self.processed_doc.toprettyxml(
			indent="\t",
			encoding="UTF-8"
		)

	def _resolve_internal_links(self, markdown_text: str) -> str:

		def resolve_link(match):
			try:
				target_finding = next(filter(
					lambda finding: finding.iid == int(match.group(1)),
					self.project.findings
				))
				return f'<a href="#{target_finding.slug}"/>';
			except StopIteration:
				return f"{match.group()}"

		return re.sub(
			r'#(\d+)',
			resolve_link,
			markdown_text
		)

	def _markdown_to_dom(
		self,
		markdown_text: str
	) -> typing.List[xml.dom.minidom.Element]:
		markdown_text = self._resolve_internal_links(markdown_text)
		html = pypandoc.convert_text(
			markdown_text,
			'html5',
			format='markdown_github',
			extra_args=[f"--id-prefix=ros{self.iid}"]
		).replace('\r\n', '\n')
		dom = xml.dom.minidom.parseString(f"<root>{html}</root>")
		return dom.firstChild.childNodes

	def write(self, path=None) -> None:
		if path is None:
			path = self.relative_path
		with open(path, "w") as file:
			print(f"writing {path}")
			file.write(self.prettyxml.decode("UTF-8"))

	@property
	def exists(self):
		return os.path.isfile(self.relative_path)

	@property
	def relative_path(self):
		return self.filename

	@property
	def filename(self):
		return f"{self.slug}.xml"

	@property
	def slug(self):
		return f"f{self.iid}-{slugify(self.title)}"


class Finding(ReportAsset):

	def __init__(
		self,
		id: int,
		iid: int,
		title: str,
		description: str="",
		technicaldescription: str="",
		impact: str="",
		recommendation: str="",
		threatlevel: str="Unknown",
		type: str="Unknown",
		status: str="none",
		project=None
	) -> None:
		super().__init__(
			id=id,
			iid=iid,
			title=title,
			project=project
		)
		self.description = description
		self.technicaldescription = technicaldescription
		self.impact = impact
		self.recommendation = recommendation
		self.threatlevel = threatlevel
		self.type = type
		self.status = status

	@property
	def doc(self):
		doc = xml.dom.minidom.Document()

		root = doc.createElement("finding");
		root.setAttribute("id", self.slug)
		root.setAttribute("number", str(self.iid))
		root.setAttribute("threatLevel", self.threatlevel)
		root.setAttribute("type", self.type)
		root.setAttribute("status", self.status)

		title = doc.createElement("title");
		title.appendChild(doc.createTextNode(self.title))
		root.appendChild(title)

		self.__append_section(root, "description")
		self.__append_section(root, "technicaldescription")
		self.__append_section(root, "impact")
		self.__append_section(root, "recommendation")

		doc.appendChild(root)
		return doc

	def __append_section(self, parentNode, name):
		section = xml.dom.minidom.Element(name)
		markdown_text = self.__getattribute__(name)
		section_nodes = self._markdown_to_dom(markdown_text)
		for node in section_nodes:
			section.appendChild(node)
		parentNode.appendChild(section)

	@property
	def relative_path(self):
		return f"findings/{self.filename}"


class NonFinding(ReportAsset):

	def __init__(
		self,
		id: int,
		iid: int,
		title: str,
		description: str="",
		project=None
	) -> None:
		super().__init__(
			id=id,
			iid=iid,
			title=title,
			project=project
		)
		self.description = description

	@property
	def doc(self):
		doc = xml.dom.minidom.Document()
		root = doc.createElement("non-finding");
		root.setAttribute("id", self.slug)
		root.setAttribute("number", str(self.iid))

		title = doc.createElement("title");
		title.appendChild(doc.createTextNode(self.title))
		root.appendChild(title)

		content_nodes = self._markdown_to_dom(self.description)
		for node in content_nodes:
			root.appendChild(node)
		doc.appendChild(root)
		return doc

	@property
	def relative_path(self):
		return f"non-findings/{self.filename}"


class ReportAssetSection(ReportAsset):

	def __init__(
		self,
		text: str,
		**kwargs
	) -> None:
		super().__init__(0, 0, self.section_title, **kwargs)
		self.text = text
		self._doc = None

	@property
	def section_title(self):
		raise NotImplementedError;

	@property
	def filename(self):
		raise NotImplementedError;

	@property
	def relative_path(self):
		return f"source/{self.filename}"

	@property
	def doc(self):
		return self._doc

	@property
	def is_user_modified(self):
		return self.text is not None

	def write(self, dest=None):
		if self.is_user_modified is False:
			print(f"No {self.title} issue found - skipping {self.relative_path}")
			return
		if dest is None:
			dest = self.relative_path

		xml_content = self.doc.toxml()
		with open(dest, "w", encoding="UTF-8") as file:
			print(f"writing {self.title} to {dest}")
			file.write(xml_content)


class Conclusion(ReportAssetSection):

	@property
	def section_title(self):
		return "Conclusion"

	@property
	def filename(self):
		return "conclusion.xml"

	@property
	def doc(self):
		if self._doc is None:
			print(f"Reading {self.title} from {self.relative_path}")
			doc = xml.dom.minidom.parse(self.relative_path)
			self._doc = self.replace_todo(doc)
		return self._doc

	def replace_todo(self, doc):
		todos = doc.documentElement.getElementsByTagName("todo")
		if len(todos) == 0:
			# skip when no <todo> element was found in XML
			return doc
		if self.text == None:
			# skip when this asset was not found in GitLab issues
			return doc

		todo = todos[0]
		if todo.parentNode.tagName == "p":
			# <p><todo/></p>
			todo = todo.parentNode

		todo.parentNode.insertBefore(doc.createComment("pentext-docker: convert"), todo)
		for node in self._markdown_to_dom(self.text):
			todo.parentNode.insertBefore(node, todo)
			todo.parentNode.insertBefore(doc.createTextNode("\n"), todo)
		todo.parentNode.insertBefore(doc.createComment("pentext-docker: convert"), todo)

		# remove empty text node before the todo item
		prev = todo.previousSibling
		if (prev is not None) and (prev.nodeType == doc.TEXT_NODE) and (len(prev.nodeValue.strip()) == 0):
			prev.parentNode.removeChild(prev)
		todo.parentNode.removeChild(todo)

		return doc


class FutureWork(ReportAssetSection):

	def __init__(
		self,
		items: typing.List[typing.Dict[str, str]],
		**kwargs
	) -> None:
		super().__init__(None, **kwargs)
		self.items = items
		self._doc = None

	@property
	def section_title(self):
		return "Future Work"

	@property
	def filename(self):
		return "futurework.xml"

	@property
	def is_user_modified(self):
		return len(self.items) > 0

	@property
	def doc(self):
		if self._doc is None:
			print(f"Reading {self.title} from {self.relative_path}")
			doc = xml.dom.minidom.parse(self.relative_path)
			self._doc = self.replace_todo(doc)
		return self._doc

	def replace_todo(self, doc):
		todos = doc.documentElement.getElementsByTagName("todo")
		if len(todos) == 0:
			# skip when no <todo> element was found in XML
			return doc
		if self.is_user_modified is False:
			# skip when no GitLab issues with 'future-work' label were found
			return doc

		todo = todos[0]
		if todo.parentNode.tagName == "li":
			# <li><todo/></li>
			todo = todo.parentNode

		todo.parentNode.insertBefore(
			doc.createComment("pentext-docker: convert"),
			todo
		)
		for item in self.items:
			futurework_item = doc.createElement("li")
			_title = doc.createElement("b")
			_title.appendChild(doc.createTextNode(item.title))
			futurework_item.appendChild(_title)
			for node in self._markdown_to_dom(item.description):
				futurework_item.appendChild(node)
				futurework_item.appendChild(doc.createTextNode("\n"))
			todo.parentNode.insertBefore(futurework_item, todo)
		todo.parentNode.insertBefore(
			doc.createComment("pentext-docker: convert"),
			todo
		)

		# remove empty text node before the todo item
		prev = todo.previousSibling
		if (prev is not None) and (prev.nodeType == doc.TEXT_NODE) and (len(prev.nodeValue.strip()) == 0):
			prev.parentNode.removeChild(prev)
		todo.parentNode.removeChild(todo)

		return doc


class ResultsInANutshell(ReportAssetSection):

	@property
	def section_title(self):
		return "Results In A Nutshell"

	@property
	def filename(self):
		return "resultsinanutshell.xml"

	@property
	def doc(self):
		doc = xml.dom.minidom.Document()

		root = doc.createElement("section")
		root.setAttribute("id", "resultsinanutshell")
		root.setAttribute("xml:base", self.filename)

		title = doc.createElement("title");
		title.appendChild(doc.createTextNode(self.title))
		root.appendChild(title)

		section_nodes = self._markdown_to_dom(self.text)
		for node in section_nodes:
			root.appendChild(node)

		doc.appendChild(root)
		return doc


class Report:

	def __init__(
		self,
		path: str="source/report.xml"
	) -> None:
		self.path = path
		self.doc = None
		self.read()

	def read(self):
		self.doc = xml.dom.minidom.parse(self.path)

	def write(self, dest=None):
		if dest is None:
			dest = self.path
		with open(dest, "w", encoding="UTF-8") as file:
			print(f"writing report to {dest}")
			file.write(self.doc.toxml())

	def get_section(self, section_name):
		for section in self.doc.documentElement.getElementsByTagName("section"):
			if section.getAttribute("id") == section_name:
				return section

	@property
	def findings(self):
		return self.get_section("findings")

	@property
	def non_findings(self):
		return self.get_section("non-findings")

	def add(self, section_name, item):
		el = self.doc.createElement("xi:include")
		el.setAttribute("xmlns:xi", "http://www.w3.org/2001/XInclude")
		el.setAttribute("href", os.path.join("..", item.relative_path))
		section = self.get_section(section_name)
		if section is None:
			print(
				f"A {section_name} section was not found in the XML file."
				f" - {section_name} will not be included."
			)
		else:
			section.appendChild(el)

	def add_finding(self, finding: Finding) -> None:
		self.add("findings", finding)

	def add_non_finding(self, non_finding: NonFinding) -> None:
		self.add("nonFindings", non_finding)


class ROSProject:

	def __init__(self, project_id: int) -> None:
		self.gitlab_project = gitlab.projects.get(project_id)
		self._findings = None
		self._non_findings = None
		self._conclusion = None
		self._resultsinanutshell = None
		self._futurework = None
		self.report = Report()

	@property
	def findings(self):
		if self._findings is None:
			self._findings = list(map(
				self.readFindingFromIssue,
				self.gitlab_project.issues.list(
					labels=["finding"],
					as_list=False
				)
			))
		return self._findings

	@property
	def non_findings(self):
		if self._non_findings is None:
			self._non_findings = list(map(
				lambda issue: NonFinding(
					id=int(issue.id),
					iid=int(issue.iid),
					title=issue.title,
					description=issue.description,
					project=self
				),
				self.gitlab_project.issues.list(
					labels=["non-finding"],
					as_list=False
				)
			))
		return self._non_findings

	@staticmethod
	def __permissive_user_input(text: str) -> str:
		return text.lower().replace(" ", "")

	@property
	def conclusion(self):
		_section = "Conclusion"
		_simplify = self.__permissive_user_input
		if self._conclusion is None:
			args = dict()
			args["search"] = _section
			args["in"] = "title"
			issues = list(filter(
				lambda issue: _simplify(issue.title) == _simplify(_section),
				self.gitlab_project.issues.list(**args)
			))
			if len(issues) > 1:
				raise Error(f"Multiple {_section} issues found on GitLab.")
			text = issues[0].description if (len(issues) == 1) else None
			self._conclusion = Conclusion(
				text=text,
				project=self
			)
		return self._conclusion

	@property
	def resultsinanutshell(self):
		_section = "Results In A Nutshell"
		_simplify = self.__permissive_user_input
		if self._resultsinanutshell is None:
			args = dict()
			args["search"] = _section
			args["in"] = "title"
			issues = list(filter(
				lambda issue: _simplify(issue.title) == _simplify(_section),
				self.gitlab_project.issues.list(**args)
			))
			if len(issues) > 1:
				raise Error(f"Multiple {_section} issues found on GitLab.")
			text = issues[0].description if (len(issues) == 1) else None
			self._resultsinanutshell = ResultsInANutshell(
				text=text,
				project=self
			)
		return self._resultsinanutshell

	@property
	def futurework(self):
		_section = "Future Work"
		_simplify = self.__permissive_user_input
		if self._futurework is None:
			self._futurework = FutureWork(
				items=self.gitlab_project.issues.list(labels=["future-work"]),
				project=self
			)
		return self._futurework

	def write(self):
		for finding in self.findings:
			if finding.exists and SKIP_EXISTING:
				continue
			finding.write()
			self.report.add_finding(finding)
		for non_finding in self.non_findings:
			if non_finding.exists and SKIP_EXISTING:
				continue
			non_finding.write();
			self.report.add_non_finding(non_finding)
		self.conclusion.write()
		self.resultsinanutshell.write()
		self.futurework.write()
		self.report.write()
		print("ROS Project written")

	def readFindingFromIssue(self, issue):
		technicaldescription = ""
		impact = ""
		recommendation = ""
		threatlevel = "Unknown"
		type = "Unknown"
		status = "none"

		i = 0
		for discussion in issue.discussions.list(as_list=False):

			notes = filter(
				lambda note: note["system"] == False,
				discussion.attributes["notes"]
			)

			try:
				comment = next(notes)["body"]
			except StopIteration:
				# skip system events without notes
				continue

			i += 1

			# the first comment is the technical description
			# unless later found explicitly
			if i == 1:
				technicaldescription = comment

			# other comments can have a meaning as well 
			lines = comment.splitlines()
			first_line = lines.pop(0).lower().strip().strip(":#")
			if first_line == "recommendation":
				recommendation = "\n".join(lines).strip()
			elif first_line == "impact":
				impact = "\n".join(lines)
			elif first_line == "type":
				type = lines[0].strip()
			elif (first_line.replace(" ", "") == "technicaldescription"):
				technicaldescription = "\n".join(lines)

		for label in issue.labels:
			if label.lower().startswith("threatlevel:") is True:
				threatlevel = label.split(":", maxsplit=1)[1]
			if label.lower().startswith("reteststatus:") is True:
				status = label.split(":", maxsplit=1)[1]

		return Finding(
			id=int(issue.id),
			iid=int(issue.iid),
			title=issue.title,
			description=issue.description,
			technicaldescription=technicaldescription,
			impact=impact,
			recommendation=recommendation,
			threatlevel=threatlevel,
			type=type,
			status=status,
			project=self
		)


project = ROSProject(os.environ["CI_PROJECT_ID"])
project.write()
