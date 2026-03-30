import zipfile
import xml.etree.ElementTree as ET

with zipfile.ZipFile('ផែនការAI Translator.docx') as docx:
    xml_content = docx.read('word/document.xml')
    tree = ET.fromstring(xml_content)
    namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs = tree.findall('.//w:p', namespaces)
    
    with open('doc_content.txt', 'w', encoding='utf-8') as f:
        for paragraph in paragraphs:
            text = ''.join(node.text for node in paragraph.findall('.//w:t', namespaces) if node.text)
            f.write(text + '\n')
