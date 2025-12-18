#!/usr/bin/env python3
"""
Contract Information Extraction Script
Extracts Principal (Payer) and Agent (Payee) from service contracts
"""

import pandas as pd
import re
from typing import Dict, Optional, Tuple


class ContractParser:
    def __init__(self):
        # OCR error corrections (common mistakes in Iowa documents)
        self.ocr_corrections = {
            r"\blowa\b": "Iowa",  # Common OCR error
            r"\bDes l\/loines\b": "Des Moines",
            r"\blVlarshall\b": "Marshall",
            r"\bCountv\b": "County",
            r"\bCitv\b": "City",
            r"\bCHickasaw\b": "Chickasaw",  # Weird capitalization
        }

        # Words that should end entity names
        self.entity_stopwords = [
            "and",
            "whereas",
            "ss",
            "the",
            "that",
            "this",
            "said",
            "agree",
            "enter",
            "contract",
            "between",
            "wishes",
            "wish",
            "provides",
            "provide",
            "shall",
            "will",
            "herein",
            "hereinafter",
        ]

        # Patterns for identifying payment relationships
        self.payment_patterns = [
            # X shall pay Y / X agrees to pay Y
            r"(?P<payer>[\w\s]+?)\s+(?:shall|agrees to|will)\s+pay\s+(?:to\s+)?(?:the\s+)?(?P<payee>[\w\s]+?)(?:\s+(?:a|an|the)\s+(?:sum|amount))",
            # Payment from X to Y
            r"payment\s+(?:shall be made\s+)?(?:from\s+)?(?:the\s+)?(?P<payer>[\w\s]+?)\s+to\s+(?:the\s+)?(?P<payee>[\w\s]+)",
            # X pays Y
            r"(?P<payer>[\w\s]+?)\s+pays?\s+(?:to\s+)?(?:the\s+)?(?P<payee>[\w\s]+?)(?:\s+(?:a|an|the)\s+(?:sum|amount|fee))",
            # Y shall be paid by X
            r"(?P<payee>[\w\s]+?)\s+shall be paid by\s+(?:the\s+)?(?P<payer>[\w\s]+)",
        ]

        # Common entity type keywords
        self.entity_keywords = [
            "County",
            "City",
            "State",
            "Agency",
            "Department",
            "District",
            "Board",
            "Commission",
            "Authority",
            "Corporation",
            "College",
            "University",
            "School",
            "Township",
            "Village",
            "Municipality",
        ]

    def preprocess_text(self, text: str) -> str:
        """
        Fix common OCR errors and standardize text
        """
        if not text:
            return text

        # Apply OCR corrections
        for error, correction in self.ocr_corrections.items():
            text = re.sub(error, correction, text, flags=re.IGNORECASE)

        return text

    def is_valid_entity_name(self, name: str) -> bool:
        """
        Validate that an entity name is reasonable and not clearly invalid
        """
        if not name or len(name.strip()) < 3:
            return False

        name_lower = name.lower()

        # Reject clearly invalid patterns
        invalid_patterns = [
            r"^county of each participant",
            r"^each participant",
            r"^participant to",
            r"^full legal name",
            r"^organization type",
            r"^party \d+",
            r"hereinafter.*to as$",
            r"^to as",
            r"^\s*(and|or|the|a|an)\s*$",
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, name_lower):
                return False

        # Reject if it's just a single organization type keyword
        if name.strip() in [kw.lower() for kw in self.entity_keywords]:
            return False

        return True

    def clean_entity_name(self, name: str) -> str:
        """
        Clean up entity names by removing pollution and standardizing format
        """
        if not name:
            return name

        # Remove leading/trailing whitespace
        name = name.strip()

        # If this looks like a sentence fragment (has verbs like "is", "will", "shall"),
        # it's probably not a proper entity name - try to extract just the entity
        sentence_patterns = [
            r"^(.+?)\s+(?:is|are|was|were|will|shall|has|have)\s+",
            r"^(.+?)\s+(?:established|organized|incorporated|created)\s+",
            r"^(.+?)\s+(?:wishes?|wish)\s+(?:to|for)",
            r"^(.+?)\s+(?:provides?|provide)\s+(?:for|to)",
        ]
        for pattern in sentence_patterns:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                break

        # Remove "hereinafter" clauses more aggressively
        name = re.sub(r"\s*\(?hereinafter[^)]*\)?\s*", " ", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+hereinafter.*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+to as\s*$", "", name, flags=re.IGNORECASE)

        # Split on stopwords and take only the first part
        name_lower = name.lower()
        for stopword in self.entity_stopwords:
            # Find the stopword with word boundaries
            pattern = rf"\b{re.escape(stopword)}\b"
            match = re.search(pattern, name_lower)
            if match:
                # Keep only the part before the stopword
                name = name[: match.start()].strip()
                break

        # Remove trailing punctuation and abbreviations that shouldn't be there
        name = re.sub(r"\s*[,;:]?\s*$", "", name)
        name = re.sub(r"\bss\s*$", "", name, flags=re.IGNORECASE)

        # Remove "State of Iowa" suffix which is redundant
        name = re.sub(r"\s+State of Iowa$", "", name, flags=re.IGNORECASE)

        # Remove office/department descriptors that shouldn't be part of the entity name
        name = re.sub(
            r"\s+(?:Office of|Department of)\s*$", "", name, flags=re.IGNORECASE
        )

        # Standardize to Title Case (except common abbreviations)
        # But preserve all-caps abbreviations like "CITY OF ELDORA"
        if name.isupper() or name.islower():
            # Convert to title case, but keep "of" lowercase
            words = name.split()
            words = [
                w.capitalize() if w.lower() not in ["of", "and", "the"] else w.lower()
                for w in words
            ]
            name = " ".join(words)

        # Final cleanup
        name = re.sub(r"\s+", " ", name).strip()

        # If name is too long (>80 chars), it's probably bad extraction
        if len(name) > 80:
            # Try to extract just City/County/Agency name
            entity_match = re.match(
                r"^(City|County|Town|Village|Township|Agency|Department|District)\s+of\s+[\w\s]+",
                name,
                re.IGNORECASE,
            )
            if entity_match:
                name = entity_match.group(0)

        return name

    def extract_entities(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract party names from the contract text.
        Returns (Party1, Party2) where we'll determine which is payer/payee later
        """
        parties = {}

        # Look for "Party 1" and "Party 2" sections (common in 28E forms)
        # In these forms, the party name is on the line immediately after "Party N"
        # Sometimes the next line is just the organization type (City, County, etc.),
        # in which case we need to look at the line after that
        lines = text.split("\n")
        for i, line in enumerate(lines):
            # Check if this line is a Party declaration
            party_match = re.match(r"Party\s+(\d+)\s*$", line.strip(), re.IGNORECASE)
            if party_match and i + 1 < len(lines):
                party_num = int(party_match.group(1))

                # Look for the party name - it might be on the next line, or the line after
                # if the next line is just an organization type keyword
                name = None
                for offset in [1, 2]:
                    if i + offset >= len(lines):
                        break
                    candidate_line = lines[i + offset].strip()

                    # Skip empty lines, Party declarations, and organization type keywords
                    if (
                        candidate_line
                        and len(candidate_line) > 2
                        and not re.match(r"Party\s+\d+", candidate_line, re.IGNORECASE)
                        and candidate_line not in self.entity_keywords
                        and not re.match(r"^\d+$", candidate_line)  # Skip county codes
                        and not re.match(
                            r"^[A-Z]{2,3}$", candidate_line
                        )  # Skip state abbreviations
                    ):
                        # Clean up the name - remove newlines and extra spaces
                        name = candidate_line.replace("\n", " ").replace("\r", " ")
                        name = re.sub(r"\s+", " ", name).strip()

                        # Validate it's a reasonable entity name
                        if self.is_valid_entity_name(name):
                            break
                        else:
                            name = None

                # Only store if we found a valid name and haven't stored this party yet
                if name and party_num not in parties:
                    parties[party_num] = name

        # If we found parties, return them in order
        if 1 in parties and 2 in parties:
            return parties[1], parties[2]
        elif 1 in parties:
            return parties[1], None
        elif 2 in parties:
            return None, parties[2]

        # the most reasonable fallback
        # Fallback 1: Look for "This agreement is entered into this by and between..." pattern
        # Pattern: "This agreement is entered into this [date], by (and) between [Entity1], and [Entity2]"
        # This handles multi-line matches and OCR variations
        # Stop entity1 at ", and" or " and" before entity2
        # Stop entity2 at ", and the", "(hereinafter", or end of sentence
        # Also handle variations like "This Agreement is made and entered into..."
        agreement_patterns = [
            r"This\s+agreement\s+is\s+entered\s+into\s+this\s+(?:\d{4}[,\s]+)?by\s+(?:and\s+)?between\s+(.+?)(?:,\s+and\s+|\s+and\s+)(.+?)(?:\(hereinafter|,\s+and\s+the\s+[A-Z]|\.\s+Whereas|\.\s*$)",
            r"This\s+agreement\s+is\s+made\s+(?:and\s+entered\s+into)?\s+(?:this\s+)?(?:\d{1,2}[a-z]{2}\s+day\s+of\s+)?(?:\w+\s+)?(?:\d{4}[,\s]+)?by\s+(?:and\s+)?between\s+(.+?)(?:,\s+and\s+|\s+and\s+)(.+?)(?:\(hereinafter|,\s+and\s+the\s+[A-Z]|\.\s+Whereas|\.\s*$)",
            r"This\s+agreement\s+\(?agreement\)?\s+is\s+made\s+(?:and\s+entered\s+into)?\s+(?:this\s+)?(?:\d{1,2}[a-z]{2}\s+day\s+of\s+)?(?:\w+\s+)?(?:\d{4}[,\s]+)?by\s+(?:and\s+)?between\s+(.+?)(?:,\s+and\s+|\s+and\s+)(.+?)(?:\(hereinafter|,\s+and\s+the\s+[A-Z]|\.\s+Whereas|\.\s*$)",
        ]
        agreement_match = None
        for pattern in agreement_patterns:
            agreement_match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if agreement_match:
                break
        if agreement_match:
            entity1_raw = agreement_match.group(1).strip()
            entity2_raw = agreement_match.group(2).strip()

            # Clean up entity names - remove "hereinafter" clauses and extra punctuation
            # Remove "(hereinafter referred to as ...)"
            entity1 = re.sub(
                r"\s*\(hereinafter[^)]*\)", "", entity1_raw, flags=re.IGNORECASE
            ).strip()
            entity2 = re.sub(
                r"\s*\(hereinafter[^)]*\)", "", entity2_raw, flags=re.IGNORECASE
            ).strip()

            # Remove OCR noise patterns like ": Jon :" or similar (but preserve colons in "City of")
            entity1 = re.sub(r":\s*[A-Z][a-z]+\s*:", " ", entity1).strip()
            entity2 = re.sub(r":\s*[A-Z][a-z]+\s*:", " ", entity2).strip()

            # Remove trailing commas, colons, and clean up whitespace
            entity1 = re.sub(r"\s*[,;:]+\s*$", "", entity1).strip()
            entity2 = re.sub(r"\s*[,;:]+\s*$", "", entity2).strip()

            # Remove state names like ", Iowa" if present
            entity1 = re.sub(
                r"\s*,\s*Iowa\s*$", "", entity1, flags=re.IGNORECASE
            ).strip()
            entity2 = re.sub(
                r"\s*,\s*Iowa\s*$", "", entity2, flags=re.IGNORECASE
            ).strip()

            # Normalize whitespace (handle newlines and multiple spaces)
            entity1 = re.sub(r"\s+", " ", entity1).strip()
            entity2 = re.sub(r"\s+", " ", entity2).strip()

            # If we have valid entities (not too short), return them
            if entity1 and len(entity1) > 3 and entity2 and len(entity2) > 3:
                return entity1, entity2
            elif entity1 and len(entity1) > 3:
                return entity1, None

        # Fallback 2: Look for explicit entity names in the text
        entity_pattern = r"(?:City|County|Town|Village|Township)\s+of\s+[\w\s]+"
        matches = re.findall(entity_pattern, text, re.IGNORECASE)
        if matches:
            # Get unique entities
            unique_entities = []
            for match in matches:
                if match not in unique_entities:
                    unique_entities.append(match)
            if len(unique_entities) >= 2:
                return unique_entities[0], unique_entities[1]
            elif len(unique_entities) == 1:
                return unique_entities[0], None

        return None, None

    def get_entity_type(self, party: str) -> Optional[str]:
        """
        Get the entity type from the party
        """
        for entity_type in [
            "sheriff",
            "township",
            "village",
            "town",
            "district",
            "city",
            "county",
            "agency",
            "department",
        ]:
            if entity_type in party.lower():
                return entity_type

    def _party_matches_text(self, party_lower: str, text_lower: str) -> bool:
        """
        Check if a party name matches text (handles substring matching both ways).
        Example: "City of Ames" matches "city of ames" or "city"
        """
        return party_lower in text_lower or text_lower in party_lower

    def extract_payment_relationship(
        self, text: str, party1: str, party2: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine which party is the payer (principal) and which is the payee (agent).

        Returns: (payer, payee) tuple

        Pattern matching order:
        1. Generic entity type patterns (e.g., "The City shall pay the County")
        2. Direct party name patterns (e.g., "Wall Lake shall pay Lake View")
        3. Payment destination patterns (e.g., "payment shall be made to City of Ames")
        4. Responsibility patterns (e.g., "City of Ames shall be responsible for payment")
        5. Fallback: count mentions near "pay" keyword
        6. Default: return original order (Party 1 as payer, Party 2 as payee)
        """
        if not party1 or not party2:
            return party1, party2

        text_lower = text.lower()
        party1_lower = party1.lower()
        party2_lower = party2.lower()

        # Pattern 1: Generic entity type patterns
        # Most contracts use generic terms like "The City shall pay the County"
        # Example: "The City shall pay the County" where parties are "City of Des Moines" and "Polk County"
        party1_type = self.get_entity_type(party1)
        party2_type = self.get_entity_type(party2)
        if party1_type and party2_type and party1_type != party2_type:
            # Define generic payment patterns: (pattern, payer_type, payee_type)
            generic_patterns = [
                (
                    r"(?:the\s+)?city.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?county",
                    "city",
                    "county",
                ),
                (
                    r"(?:the\s+)?county.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?city",
                    "county",
                    "city",
                ),
                (
                    r"(?:the\s+)?city.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?sheriff",
                    "city",
                    "sheriff",
                ),
                (
                    r"(?:the\s+)?sheriff.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?city",
                    "sheriff",
                    "city",
                ),
            ]

            for pattern, payer_type, payee_type in generic_patterns:
                if re.search(pattern, text_lower):
                    if party1_type == payer_type and party2_type == payee_type:
                        return party1, party2
                    elif party2_type == payer_type and party1_type == payee_type:
                        return party2, party1

        # Pattern 2: Direct "X shall pay Y" patterns (handles both specific names and generic terms)
        # Examples:
        #   - "Wall Lake shall pay Lake View"
        #   - "City of Ames shall pay Story County"
        #   - "The City shall pay the County" (when entity types don't match)
        payment_verb_pattern = r"(?:shall|will|agrees?\s+to)\s+pay\s+(?:to\s+)?"

        # Check if party1 pays party2 (handles multi-line matches with DOTALL)
        # Limit search window to ~100 chars before "shall pay" and ~100 chars after to prevent
        # matching across the entire document. This ensures we only match within the same payment clause.
        pattern1 = rf"{re.escape(party1_lower)}.{{0,100}}?{payment_verb_pattern}.{{0,100}}?{re.escape(party2_lower)}"
        if re.search(pattern1, text_lower, re.DOTALL):
            return party1, party2

        # Check if party2 pays party1
        # Same window limitation to prevent cross-document matching
        pattern2 = rf"{re.escape(party2_lower)}.{{0,100}}?{payment_verb_pattern}.{{0,100}}?{re.escape(party1_lower)}"
        if re.search(pattern2, text_lower, re.DOTALL):
            return party2, party1

        # Also check for generic "the X" patterns (handles articles)
        # Example: "The City shall pay the County" when both parties have "the" prefix
        generic_pay_pattern = rf"(?:the\s+)?(\w+(?:\s+\w+)*?)\s+{payment_verb_pattern}(?:the\s+)?(\w+(?:\s+\w+)*?)"
        for match in re.finditer(generic_pay_pattern, text_lower):
            payer_text = match.group(1).strip()
            payee_text = match.group(2).strip()

            if self._party_matches_text(party1_lower, payer_text):
                if self._party_matches_text(party2_lower, payee_text):
                    return party1, party2
            elif self._party_matches_text(party2_lower, payer_text):
                if self._party_matches_text(party1_lower, payee_text):
                    return party2, party1

        # Pattern 3: "payment shall be made to Y" - Y is the payee
        # Example: "Payment shall be made to City of Ames" -> Story County pays City of Ames
        payment_to_pattern = (
            r"payment.*?(?:shall be )?made.*?to.*?(?:the\s+)?(\w+(?:\s+\w+)*?)"
        )
        for match in re.finditer(payment_to_pattern, text_lower):
            payee_text = match.group(1)
            if self._party_matches_text(party1_lower, payee_text):
                return party2, party1
            elif self._party_matches_text(party2_lower, payee_text):
                return party1, party2

        # Pattern 4: "X shall be responsible for the payment" - X is the payer
        # Example: "City of Ames shall be responsible for the payment" -> City of Ames pays
        responsible_pattern = r"(\w+(?:\s+\w+)*?)\s+shall be responsible for.*?payment"
        for match in re.finditer(responsible_pattern, text_lower):
            payer_text = match.group(1)
            if self._party_matches_text(party1_lower, payer_text):
                return party1, party2
            elif self._party_matches_text(party2_lower, payer_text):
                return party2, party1

        # Fallback: Count mentions near "pay" keyword
        # The party mentioned more often in payment context is likely the payer
        # Example: "City of Ames will pay... City of Ames agrees to pay..." -> City of Ames likely pays
        party1_pay_count = len(
            re.findall(rf"{re.escape(party1_lower)}.{{0,100}}pay", text_lower)
        )
        party2_pay_count = len(
            re.findall(rf"{re.escape(party2_lower)}.{{0,100}}pay", text_lower)
        )

        if party1_pay_count > party2_pay_count:
            return party1, party2
        elif party2_pay_count > party1_pay_count:
            return party2, party1

        return party1, party2

    def parse_contract(self, text: str, pdf_id: str) -> Dict[str, any]:
        """
        Parse a single contract and extract principal and agent
        """
        if not text or pd.isna(text):
            return {"PDF_ID": pdf_id, "principal": "", "agent": ""}

        # Preprocess text to fix OCR errors
        text = self.preprocess_text(text)

        # Extract parties
        party1, party2 = self.extract_entities(text)
        # Determine payment relationship
        if party1 and party2:
            principal, agent = self.extract_payment_relationship(text, party1, party2)
        else:
            principal = party1 if party1 else ""
            agent = party2 if party2 else ""

        # Clean up entity names - remove any remaining newlines and pollution
        if principal:
            principal = principal.replace("\n", " ").replace("\r", " ")
            principal = re.sub(r"\s+", " ", principal).strip()
            principal = self.clean_entity_name(principal)
            # Validate and reject if clearly invalid
            if not self.is_valid_entity_name(principal):
                principal = ""
        if agent:
            agent = agent.replace("\n", " ").replace("\r", " ")
            agent = re.sub(r"\s+", " ", agent).strip()
            agent = self.clean_entity_name(agent)
            # Validate and reject if clearly invalid
            if not self.is_valid_entity_name(agent):
                agent = ""

        return {
            "PDF_ID": pdf_id,
            "principal": principal if principal else "",
            "agent": agent if agent else "",
        }


def main():
    df = pd.read_csv("ocr_contracts.csv")
    parser = ContractParser()
    results = []

    for idx, row in df.iterrows():
        pdf_id = row["PDF_ID"]
        text = row["surya_ocr"]

        result = parser.parse_contract(text, pdf_id)
        results.append(result)

    output_df = pd.DataFrame(results)
    output_df = output_df[["PDF_ID", "principal", "agent"]]
    output_path = "extracted_entities.csv"
    output_df.to_csv(output_path, index=False)


if __name__ == "__main__":
    main()
