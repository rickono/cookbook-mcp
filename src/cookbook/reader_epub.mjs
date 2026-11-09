/* Match the archive-root path retained by ingestion, never a filename suffix. */
export function spineItemForDocument(items, document, origin, occurrence) {
  const matches = items.filter(item => {
    if (typeof item.url !== 'string') return false;
    try {
      const url = new URL(item.url, origin + '/');
      if (url.origin !== origin) return false;
      const path = decodeURIComponent(url.pathname.replace(/%(?![0-9a-f]{2})/gi, '%25')).replace(/^\//, '');
      return path === document && (occurrence === undefined || item.index === occurrence);
    } catch { return false; }
  });
  if (matches.length !== 1) throw Error('Exact source document unavailable or ambiguous');
  return matches[0];
}

// Layout changes attributes on the body, but must not change its source tree
// before a positional XPath can identify the same node in both documents.
function unchangedBody(source, rendered) {
  if (!source || !rendered) return false;
  const pairs = [[source, rendered]];
  const children = node => Array.from(node.childNodes).filter(child => [1, 3, 4].includes(child.nodeType));
  while (pairs.length) {
    const [a, b] = pairs.pop();
    if (a.nodeType === 1 && b.nodeType === 1) {
      if (a.localName !== b.localName || a.namespaceURI !== b.namespaceURI) return false;
      const ac = children(a), bc = children(b);
      if (ac.length !== bc.length) return false;
      for (let index = 0; index < ac.length; index++) pairs.push([ac[index], bc[index]]);
    } else if (a.nodeType === 1 || b.nodeType === 1 || a.textContent !== b.textContent) return false;
  }
  return true;
}

function uniqueAnchor(document, anchor) {
  const matches = Array.from(document.querySelectorAll('[id]')).filter(node => node.getAttribute('id') === anchor);
  if (matches.length !== 1) throw Error('Exact source anchor unavailable or ambiguous');
  return matches[0];
}

const nodeAtXPath = (document, xpath) => document.evaluate(xpath, document, prefix => document.documentElement.lookupNamespaceURI(prefix), 9, null).singleNodeValue;

export async function displayEpubDestination(book, rendition, destination, origin) {
  let item, sourceDocument;
  if (destination.epub_document) {
    item = spineItemForDocument(book.spine.spineItems, destination.epub_document, origin, destination.epub_occurrence);
    if (destination.epub_anchor || destination.epub_xpath) {
      const element = await item.load(book.load.bind(book));
      sourceDocument = element.ownerDocument || element;
      if (destination.epub_anchor) {
        const anchor = uniqueAnchor(sourceDocument, destination.epub_anchor);
        if (destination.epub_xpath && nodeAtXPath(sourceDocument, destination.epub_xpath) !== anchor) throw Error('Source anchor does not identify the retained node');
      }
    }
  }
  // Href lookup aliases repeated documents and percent/space filenames.
  // Numeric indices preserve the already-validated occurrence, including zero.
  const displayed = await rendition.display(item?.index);
  if (!item) return;
  const content = rendition.getContents().find(content => content.sectionIndex === item.index);
  if (displayed.index !== item.index || !content) throw Error('Exact source occurrence unavailable');
  const document = content.document;
  let node;
  if (destination.epub_anchor) {
    node = uniqueAnchor(document, destination.epub_anchor);
  } else if (destination.epub_xpath) {
    if (!unchangedBody(sourceDocument.querySelector('body'), document.body)) throw Error('Source structure changed during rendering');
    const sourceNode = nodeAtXPath(sourceDocument, destination.epub_xpath);
    node = nodeAtXPath(document, destination.epub_xpath);
    if (!sourceNode || !sourceDocument.querySelector('body').contains(sourceNode) || !document.body.contains(node)) throw Error('Exact source node unavailable');
  }
  if (destination.epub_anchor || destination.epub_xpath) {
    if (!node) throw Error('Exact source node unavailable');
    const positioned = await rendition.display(content.cfiFromNode(node));
    if (positioned.index !== item.index || !rendition.getContents().some(content => content.sectionIndex === item.index)) throw Error('Exact source occurrence unavailable');
  }
}
