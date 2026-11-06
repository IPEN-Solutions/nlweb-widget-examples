import json

from nlweb_widget import ContentDocument, NLWebRequest, NLWebWidget


async def run(domain: str, example_name: str) -> None:
    widget = NLWebWidget(domain=domain)
    await widget.index(
        ContentDocument(
            id="demo",
            url=f"{domain}/authoritative",
            title=example_name,
            content="Authoritative domain information for the example scenario.",
            schema_object={"@type": "Service", "name": example_name},
        )
    )
    result = await widget.ask(NLWebRequest(query={"text": "services for companies"}))
    print("=== MOCK AI-SEARCH VISIBILITY ===")
    print(
        json.dumps(
            {
                "domain": domain,
                "indexed": len(result.results),
                "visible_urls": [item.url for item in result.results],
                "mock_visibility_rank": 1 if result.results else None,
                "note": "Deterministic demo; not a real search-engine ranking.",
            },
            indent=2,
        )
    )
