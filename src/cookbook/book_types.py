"""DRAFT whole-book types. No content processing, OCR, inference or network."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Id = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class FieldValue[T](StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {
                        "properties": {"state": {"enum": ["candidate", "supported"]}}
                    },
                    "then": {
                        "properties": {
                            "value": {"not": {"type": "null"}},
                            "evidence_span_ids": {"minItems": 1},
                        }
                    },
                    "else": {
                        "properties": {
                            "value": {"type": "null"},
                            "reason": {"type": "string", "minLength": 1},
                        }
                    },
                }
            ]
        },
    )
    state: Literal[
        "unparsed", "source_unspecified", "candidate", "supported", "unresolved"
    ]
    value: T | None
    evidence_span_ids: list[Id]
    reason: str | None

    @model_validator(mode="after")
    def honest_state(self):
        populated = self.state in ("candidate", "supported")
        if populated and (self.value is None or not self.evidence_span_ids):
            raise ValueError("A populated field requires a value and source evidence")
        if not populated and self.value is not None:
            raise ValueError("Absent/unresolved field cannot carry an asserted value")
        if not populated and not self.reason:
            raise ValueError("Absent/unresolved field requires an explanation")
        return self


class Rational(StrictModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(gt=0)


class QuantityBasis(StrictModel):
    kind: Literal["per_serving", "per_item", "per_batch"]
    wording: str


class MeasuredQuantity(StrictModel):
    kind: Literal["measured"]
    amount: Rational
    unit: str | None
    qualifiers: list[str]
    basis: QuantityBasis | None = None


class SumQuantity(StrictModel):
    kind: Literal["sum"]
    terms: list["QuantityExpression"] = Field(min_length=2)


class EquivalentQuantity(StrictModel):
    kind: Literal["equivalent"]
    forms: list["QuantityExpression"] = Field(min_length=2)


class AlternativeQuantity(StrictModel):
    kind: Literal["alternative"]
    choices: list["QuantityExpression"] = Field(min_length=2)


class RangeQuantity(StrictModel):
    kind: Literal["range"]
    lower: MeasuredQuantity
    upper: MeasuredQuantity

    @model_validator(mode="after")
    def ordered(self):
        if (
            self.lower.unit == self.upper.unit
            and self.lower.amount.numerator * self.upper.amount.denominator
            > self.upper.amount.numerator * self.lower.amount.denominator
        ):
            raise ValueError("Quantity range is reversed")
        return self


class QualitativeQuantity(StrictModel):
    kind: Literal["qualitative"]
    wording: str


class PreparationFraction(StrictModel):
    kind: Literal["preparation_fraction"]
    fraction: Rational
    recipe_use_id: Id


QuantityExpression = Annotated[
    MeasuredQuantity
    | SumQuantity
    | EquivalentQuantity
    | AlternativeQuantity
    | RangeQuantity
    | QualitativeQuantity
    | PreparationFraction,
    Field(discriminator="kind"),
]
for cls in (SumQuantity, EquivalentQuantity, AlternativeQuantity):
    cls.model_rebuild()


class Edition(StrictModel):
    id: Id
    publication_id: Id
    title: str
    authors: list[str]
    source_id: str
    source_sha256: Sha
    format: Literal["EPUB"]
    model_version: Literal["whole-book-draft-v1"]


class Resource(StrictModel):
    id: Id
    edition_id: Id
    path: str
    media_type: str | None
    byte_size: int = Field(ge=0)
    role: Literal[
        "document", "image", "style", "font", "package", "navigation", "other"
    ]
    # Source hash+member protects identity; ZIP CRC is inventory data, not SHA proof.
    zip_crc32: int | None


class SourceDocument(StrictModel):
    id: Id
    edition_id: Id
    resource_id: Id
    path: str
    root_node_id: Id
    body_text_sha256: Sha
    parser_diagnostics: list[str]


class ReadingOccurrence(StrictModel):
    id: Id
    edition_id: Id
    document_id: Id
    ordinal: int = Field(ge=0)
    linear: bool


class TextNode(StrictModel):
    kind: Literal["text"]
    id: Id
    document_id: Id
    parent_id: Id
    child_ordinal: int = Field(ge=0)
    preorder: int = Field(ge=0)
    source_xpath: str
    source_slot: Literal["text", "tail"]
    text: str


class ElementNode(StrictModel):
    kind: Literal["element"]
    id: Id
    document_id: Id
    parent_id: Id | None
    child_ordinal: int = Field(ge=0)
    preorder: int = Field(ge=0)
    subtree_end: int = Field(ge=0)
    source_xpath: str
    source_tag: str
    content_kind: Literal[
        "document",
        "paragraph",
        "heading",
        "list",
        "list_item",
        "table",
        "table_section",
        "table_row",
        "table_cell",
        "figure",
        "image",
        "caption",
        "aside",
        "quotation",
        "code",
        "line_break",
        "link",
        "emphasis",
        "math",
        "non_reading",
        "container",
        "unclassified",
    ]
    source_attributes: dict[str, str]
    child_ids: list[Id]
    heading_level: int | None = Field(default=None, ge=1, le=6)
    list_kind: Literal["ordered", "unordered", "definition"] | None = None
    table_row_span: int | None = Field(default=None, ge=1)
    table_column_span: int | None = Field(default=None, ge=1)
    asset_resource_id: Id | None = None
    alt_text: str | None = None


ContentNode = Annotated[TextNode | ElementNode, Field(discriminator="kind")]


class NodePosition(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"side": {"const": "text_offset"}}},
                    "then": {
                        "required": ["offset"],
                        "properties": {"offset": {"type": "integer", "minimum": 0}},
                    },
                    "else": {"properties": {"offset": {"type": "null"}}},
                }
            ]
        },
    )
    node_id: Id
    side: Literal["before", "after", "text_offset"]
    offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def offset_kind(self):
        if (self.side == "text_offset") != (self.offset is not None):
            raise ValueError("Only text_offset positions carry offsets")
        return self


class SpanPart(StrictModel):
    document_id: Id
    reading_occurrence_id: Id | None
    start: NodePosition
    end: NodePosition


class SourceSpan(StrictModel):
    id: Id
    edition_id: Id
    parts: list[SpanPart] = Field(min_length=1)
    locator_version: Literal["source-dom-v1"]


class LinkTarget(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"state": {"const": "resolved_node"}}},
                    "then": {
                        "properties": {
                            k: {"type": "string"}
                            for k in ["resource_id", "document_id", "node_id"]
                        }
                    },
                },
                {
                    "if": {"properties": {"state": {"const": "resolved_resource"}}},
                    "then": {
                        "properties": {
                            "resource_id": {"type": "string"},
                            "node_id": {"type": "null"},
                        }
                    },
                },
                {
                    "if": {
                        "properties": {"state": {"enum": ["external", "unresolved"]}}
                    },
                    "then": {
                        "properties": {"reason": {"type": "string", "minLength": 1}}
                    },
                },
                {
                    "if": {"properties": {"state": {"const": "external"}}},
                    "then": {
                        "properties": {
                            k: {"type": "null"}
                            for k in ["resource_id", "document_id", "node_id"]
                        }
                    },
                },
            ]
        },
    )
    state: Literal["resolved_node", "resolved_resource", "external", "unresolved"]
    resource_id: Id | None
    document_id: Id | None
    node_id: Id | None
    uri: str
    reason: str | None

    @model_validator(mode="after")
    def target_state(self):
        if self.state == "resolved_node" and not (
            self.resource_id and self.document_id and self.node_id
        ):
            raise ValueError(
                "Resolved node target requires resource/document/node identities"
            )
        if self.state == "resolved_resource" and (not self.resource_id or self.node_id):
            raise ValueError(
                "Resolved resource target requires resource identity and no node"
            )
        if self.state in ("external", "unresolved") and not self.reason:
            raise ValueError("Nonresolved target requires an explanation")
        if self.state == "external" and any(
            (self.resource_id, self.document_id, self.node_id)
        ):
            raise ValueError("External target cannot reference internal content")
        return self


class SourceLink(StrictModel):
    id: Id
    document_id: Id
    node_id: Id
    relation: Literal["hyperlink", "image_source", "note_link", "other"]
    target: LinkTarget


class NavigationEntry(StrictModel):
    id: Id
    edition_id: Id
    parent_id: Id | None
    ordinal: int = Field(ge=0)
    kind: Literal["toc", "landmark", "page_list", "ncx", "other"]
    label: str
    source_resource_id: Id
    source_xpath: str
    target: LinkTarget


class SemanticBase(StrictModel):
    id: Id
    edition_id: Id
    evidence_span_ids: list[Id] = Field(min_length=1)
    state: Literal["candidate", "supported", "unresolved"]
    method: str


class ContentDivision(SemanticBase):
    kind: Literal["division"]
    division_kind: Literal[
        "part", "chapter", "section", "front_matter", "back_matter", "unresolved"
    ]
    parent_division_id: Id | None
    title: FieldValue[str]
    content_span_ids: list[Id]


class Passage(SemanticBase):
    kind: Literal["passage"]
    passage_kind: Literal[
        "essay",
        "technique",
        "headnote",
        "sidebar",
        "note",
        "glossary",
        "index",
        "menu",
        "quotation",
        "prose",
        "troubleshooting",
        "make_ahead",
        "unresolved",
    ]
    title: FieldValue[str]
    content_span_ids: list[Id]


class ReferenceEntry(SemanticBase):
    kind: Literal["reference_entry"]
    entry_kind: Literal[
        "ingredient",
        "wine",
        "region",
        "cuisine",
        "equipment",
        "technique",
        "subject",
        "unresolved",
    ]
    label: FieldValue[str]
    content_span_ids: list[Id]


class Recipe(SemanticBase):
    kind: Literal["recipe"]
    title: FieldValue[str]
    content_span_ids: list[Id]
    yield_value: FieldValue[QuantityExpression]
    main_text_state: Literal["unchecked", "bounded", "unresolved"]
    parsed_fields_state: Literal["unparsed", "partial", "reviewed"]
    supporting_work_state: Literal["unchecked", "partial", "reviewed", "unresolved"]


class RecipePart(SemanticBase):
    kind: Literal["recipe_part"]
    recipe_id: Id
    parent_part_id: Id | None
    part_kind: Literal[
        "preparation",
        "ingredient_group",
        "method_group",
        "equipment",
        "assembly",
        "variation",
        "unresolved",
    ]
    label: FieldValue[str]
    ordinal: int = Field(ge=0)
    content_span_ids: list[Id]


class RecipeIngredient(SemanticBase):
    kind: Literal["recipe_ingredient"]
    recipe_id: Id
    part_id: Id | None
    ordinal: int = Field(ge=0)
    source_span_ids: list[Id]
    ingredient_name: FieldValue[str]
    quantity: FieldValue[QuantityExpression]
    preparation: FieldValue[str]
    recipe_use_id: Id | None
    formulation_ids: list[Id]
    formulation_state: Literal["unparsed", "common", "selected", "unresolved"]


class Instruction(SemanticBase):
    kind: Literal["instruction"]
    recipe_id: Id
    part_id: Id | None
    ordinal: int = Field(ge=0)
    source_span_ids: list[Id]
    formulation_ids: list[Id]
    formulation_state: Literal["unparsed", "common", "selected", "unresolved"]


class RecipeUse(SemanticBase):
    kind: Literal["recipe_use"]
    source_recipe_id: Id
    target_recipe_id: Id | None
    source_link_id: Id | None
    source_part_id: Id | None = None
    selected_formulation_id: Id | None = None
    selected_part_id: Id | None = None
    classification: FieldValue[
        Literal["required", "optional", "alternative", "context", "technique_reference"]
    ]
    amount_used: FieldValue[QuantityExpression]
    scope: FieldValue[Literal["whole", "partial", "variation"]]
    scope_wording: FieldValue[str]
    modification_wording: FieldValue[str]


class RecipeChoice(SemanticBase):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "anyOf": [
                {"properties": {"member_use_ids": {"minItems": 2}}},
                {"properties": {"other_option_wordings": {"minItems": 2}}},
                {
                    "properties": {
                        "member_use_ids": {"minItems": 1},
                        "other_option_wordings": {"minItems": 1},
                    }
                },
            ]
        },
    )
    kind: Literal["recipe_choice"]
    recipe_id: Id
    choice_kind: Literal["sourcing", "preparation", "variation", "unresolved"]
    member_use_ids: list[Id]
    other_option_wordings: list[FieldValue[str]]
    selection_wording: FieldValue[str]

    @model_validator(mode="after")
    def choices(self):
        if len(self.member_use_ids) + len(self.other_option_wordings) < 2:
            raise ValueError("A choice group requires at least two options")
        return self


class RecipeFormulation(SemanticBase):
    kind: Literal["recipe_formulation"]
    recipe_id: Id
    label: FieldValue[str]
    yield_value: FieldValue[QuantityExpression]
    content_span_ids: list[Id]


class IngredientAllocation(SemanticBase):
    kind: Literal["ingredient_allocation"]
    recipe_ingredient_id: Id
    instruction_id: Id | None
    stage_wording: FieldValue[str]
    amount_used: FieldValue[QuantityExpression]


class Attribution(SemanticBase):
    kind: Literal["attribution"]
    passage_id: Id
    speaker_label: FieldValue[str]
    role_wording: FieldValue[str]
    intermediary_wording: FieldValue[str]


class AttributeAssertion(SemanticBase):
    kind: Literal["attribute_assertion"]
    subject_entry_id: Id
    attribute_label: FieldValue[str]
    attribute_value: FieldValue[str]


class PairingAssertion(SemanticBase):
    kind: Literal["pairing_assertion"]
    subject_entry_id: Id
    participants: list[FieldValue[str]] = Field(min_length=2)
    recommendation_wording: FieldValue[str]
    attribution_entity_id: Id | None
    ranking_wording: FieldValue[str]
    ranking_basis_span_ids: list[Id]


SemanticEntity = Annotated[
    ContentDivision
    | Passage
    | ReferenceEntry
    | Recipe
    | RecipePart
    | RecipeIngredient
    | Instruction
    | RecipeUse
    | RecipeChoice
    | RecipeFormulation
    | IngredientAllocation
    | Attribution
    | AttributeAssertion
    | PairingAssertion,
    Field(discriminator="kind"),
]


class SemanticRelation(StrictModel):
    id: Id
    edition_id: Id
    relation: Literal[
        "contained_in",
        "about",
        "see_also",
        "attributed_to",
        "variation_of",
        "note_for",
        "caption_for",
        "ingredient_used_in_instruction",
        "geographic_part_of",
    ]
    source_entity_id: Id
    target_entity_id: Id | None
    target_label: FieldValue[str]
    evidence_span_ids: list[Id] = Field(min_length=1)
    state: Literal["candidate", "supported", "unresolved"]


class UnresolvedContent(StrictModel):
    id: Id
    edition_id: Id
    scope_id: Id
    code: Literal[
        "parser_diagnostic",
        "unresolved_link",
        "unresolved_asset",
        "unclassified_content",
        "image_text_unread",
        "ambiguous_semantics",
        "unparsed_field",
        "incomplete_source_span",
    ]
    explanation: str
    evidence_span_ids: list[Id]


class Coverage(StrictModel):
    resource_inventory_complete: bool
    reading_occurrences_complete: bool
    source_tree_complete: bool
    native_body_text_roundtrip: bool
    image_occurrences: int = Field(ge=0)
    readable_image_text_state: Literal["not_assessed", "partial", "reviewed"]
    semantic_state: Literal["not_assessed", "partial", "reviewed"]
    unresolved_ids: list[Id]


class ModelSnapshot(StrictModel):
    id: Id
    source_publication_id: Id
    extractor_version: str
    interpretation_version: str
    locator_version: Literal["source-dom-v1"]
    implementation_sha256: Sha


class WholeBook(StrictModel):
    schema_version: Literal["whole-book-draft-v1"]
    model_snapshot: ModelSnapshot
    edition: Edition
    resources: list[Resource]
    documents: list[SourceDocument]
    reading_order: list[ReadingOccurrence]
    nodes: list[ContentNode]
    source_spans: list[SourceSpan]
    source_links: list[SourceLink]
    navigation: list[NavigationEntry]
    semantic_entities: list[SemanticEntity]
    semantic_relations: list[SemanticRelation]
    unresolved_content: list[UnresolvedContent]
    coverage: Coverage
