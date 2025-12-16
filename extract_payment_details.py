#!/usr/bin/env python3
"""
Contract Information Extraction Script
Extracts Principal (Payer), Agent (Payee), and Amount from service contracts
"""

import pandas as pd
import re
from typing import Dict, Optional, Tuple
import json

class ContractParser:
    def __init__(self):
        # OCR error corrections (common mistakes in Iowa documents)
        self.ocr_corrections = {
            r'\blowa\b': 'Iowa', # very common error
            r'\bCountv\b': 'County',
            r'\bCitv\b': 'City',
            r'\bCHickasaw\b': 'Chickasaw',
        }
        
        # Words that should end entity names
        self.entity_stopwords = [
            'and', 'whereas', 'ss', 'the', 'that', 'this', 'said',
            'agree', 'enter', 'contract', 'between'
        ]
        
        # Patterns for identifying payment relationships
        self.payment_patterns = [
            # X shall pay Y / X agrees to pay Y
            r'(?P<payer>[\w\s]+?)\s+(?:shall|agrees to|will)\s+pay\s+(?:to\s+)?(?:the\s+)?(?P<payee>[\w\s]+?)(?:\s+(?:a|an|the)\s+(?:sum|amount))',
            # Payment from X to Y
            r'payment\s+(?:shall be made\s+)?(?:from\s+)?(?:the\s+)?(?P<payer>[\w\s]+?)\s+to\s+(?:the\s+)?(?P<payee>[\w\s]+)',
            # X pays Y
            r'(?P<payer>[\w\s]+?)\s+pays?\s+(?:to\s+)?(?:the\s+)?(?P<payee>[\w\s]+?)(?:\s+(?:a|an|the)\s+(?:sum|amount|fee))',
            # Y shall be paid by X
            r'(?P<payee>[\w\s]+?)\s+shall be paid by\s+(?:the\s+)?(?P<payer>[\w\s]+)',
        ]
        
        # Patterns for dollar amounts
        self.amount_patterns = [
            # Direct dollar amount: $X,XXX.XX
            r'\$\s*(?P<amount>[\d,]+\.?\d*)',
            # Written out: XXX dollars
            r'(?P<amount>[\d,]+\.?\d*)\s+[Dd]ollars?',
            # Sum of $X
            r'sum of \$\s*(?P<amount>[\d,]+\.?\d*)',
            # Amount of $X
            r'amount of \$\s*(?P<amount>[\d,]+\.?\d*)',
            # Total sum: $X
            r'[Tt]otal [Ss]um[:\s]+\$\s*(?P<amount>[\d,]+\.?\d*)',
        ]
        
        # Patterns for calculating total amounts
        self.rate_patterns = [
            # $X per capita
            r'\$\s*(?P<rate>[\d,]+\.?\d*)\s+per [Cc]apita.*?(?P<pop>[\d,]+)\s+(?:census|population)',
            # $X per month
            r'\$\s*(?P<rate>[\d,]+\.?\d*)\s+per [Mm]onth',
            # $X per hour for Y hours
            r'\$\s*(?P<rate>[\d,]+\.?\d*)\s+per [Hh]our.*?(?P<hours>[\d,]+)\s+hours',
        ]
        
        # Common entity type keywords
        self.entity_keywords = [
            'County', 'City', 'State', 'Agency', 'Department', 'District',
            'Board', 'Commission', 'Authority', 'Corporation', 'College',
            'University', 'School', 'Township', 'Village', 'Municipality'
        ]

    def clean_amount(self, amount_str: str) -> float:
        """Convert amount string to float"""
        try:
            # Remove commas and convert to float
            cleaned = amount_str.replace(',', '').strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            return 0.0

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
            r'^(.+?)\s+(?:is|are|was|were|will|shall|has|have)\s+',
            r'^(.+?)\s+(?:established|organized|incorporated|created)\s+',
        ]
        for pattern in sentence_patterns:
            match = re.match(pattern, name, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                break
        
        # Split on stopwords and take only the first part
        name_lower = name.lower()
        for stopword in self.entity_stopwords:
            # Find the stopword with word boundaries
            pattern = rf'\b{re.escape(stopword)}\b'
            match = re.search(pattern, name_lower)
            if match:
                # Keep only the part before the stopword
                name = name[:match.start()].strip()
                break
        
        # Remove trailing punctuation and abbreviations that shouldn't be there
        name = re.sub(r'\s*[,;:]?\s*$', '', name)
        name = re.sub(r'\bss\s*$', '', name, flags=re.IGNORECASE)
        
        # Remove "State of Iowa" suffix which is redundant
        name = re.sub(r'\s+State of Iowa$', '', name, flags=re.IGNORECASE)
        
        # Remove office/department descriptors that shouldn't be part of the entity name
        name = re.sub(r'\s+(?:Office of|Department of)\s*$', '', name, flags=re.IGNORECASE)
        
        # Standardize to Title Case (except common abbreviations)
        # But preserve all-caps abbreviations like "CITY OF ELDORA"
        if name.isupper() or name.islower():
            # Convert to title case, but keep "of" lowercase
            words = name.split()
            words = [w.capitalize() if w.lower() not in ['of', 'and', 'the'] else w.lower() 
                    for w in words]
            name = ' '.join(words)
        
        # Final cleanup
        name = re.sub(r'\s+', ' ', name).strip()
        
        # If name is too long (>80 chars), it's probably bad extraction
        if len(name) > 80:
            # Try to extract just City/County/Agency name
            entity_match = re.match(r'^(City|County|Town|Village|Township|Agency|Department|District)\s+of\s+[\w\s]+', 
                                   name, re.IGNORECASE)
            if entity_match:
                name = entity_match.group(0)
        
        return name

    def extract_entities(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract party names from the contract text.
        Returns (Party1, Party2) where we'll determine which is payer/payee later
        IMPORTANT LIMITATION: Contracts contain more than 2 parties - 5 in total
        """
        parties = {}
        print("extracting parties")
        # Looking for the the party name immediately after "Party N"
        lines = text.split('\n')
        for i, line in enumerate(lines):
            # Check if this line is a Party declaration
            party_match = re.match(r'Party\s+(\d+)\s*$', line.strip(), re.IGNORECASE)
            if party_match and i + 1 < len(lines):

                print(f"Party match: {party_match.group(1)}")
                party_num = int(party_match.group(1))
                # The next non-empty line should be the party name
                next_line = lines[i + 1].strip()
                # Skip if it's another Party declaration or an organization type keyword
                if (next_line and 
                    party_num not in parties and 
                    len(next_line) > 2 and 
                    not re.match(r'Party\s+\d+', next_line, re.IGNORECASE) and
                    next_line not in self.entity_keywords):
                    # Clean up the name - remove newlines and extra spaces
                    name = next_line.replace('\n', ' ').replace('\r', ' ')
                    name = re.sub(r'\s+', ' ', name).strip()
                    parties[party_num] = name
        
        # If we found parties, return them in order
        if 1 in parties and 2 in parties:
            return parties[1], parties[2]
        elif 1 in parties:
            return parties[1], None
        elif 2 in parties:
            return None, parties[2]
        
        # Fallback: Look for explicit entity names in the text
        entity_pattern = r'(?:City|County|Town|Village|Township)\s+of\s+[\w\s]+'
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

    def extract_payment_relationship(self, text: str, party1: str, party2: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Determine which party is the payer (principal) and which is the payee (agent)
        """
        if not party1 or not party2:
            return party1, party2
        print('extracting relationships')
        text_lower = text.lower()
        party1_lower = party1.lower()
        party2_lower = party2.lower()
        print(party1_lower)
        print(party2_lower)
        # CRITICAL: Determine party types (City, County, etc.) FIRST
        # Most contracts use generic terms like "The City shall pay the County"
        party1_type = None
        party2_type = None
        for entity_type in ['city', 'county', 'town', 'village', 'township', 'district', 'agency', 'department', 'sheriff']:
            print(entity_type)
            if entity_type in party1_lower:
                party1_type = entity_type
                break
        for entity_type in ['city', 'county', 'town', 'village', 'township', 'district', 'agency', 'department', 'sheriff']:
            print(entity_type)
            if entity_type in party2_lower:
                party2_type = entity_type
                break
        
        # Pattern 0: "The City shall pay the County" - THE MOST COMMON PATTERN
        # This MUST be checked BEFORE trying to match exact names
        if party1_type and party2_type and party1_type != party2_type:
            # Look for generic payment patterns
            patterns_to_check = [
                (r'(?:the\s+)?city.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?county', 'city', 'county'),
                (r'(?:the\s+)?county.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?city', 'county', 'city'),
                (r'(?:the\s+)?city.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?sheriff', 'city', 'sheriff'),
                (r'(?:the\s+)?sheriff.*?(?:shall|will|agrees?\s+to)\s+pay.*?(?:to\s+)?(?:the\s+)?city', 'sheriff', 'city'),
            ]
            
            for pattern, payer_type, payee_type in patterns_to_check:
                if re.search(pattern, text_lower):
                    # Map the generic terms to our specific parties
                    if party1_type == payer_type and party2_type == payee_type:
                        return party1, party2  # Party1 pays Party2
                    elif party2_type == payer_type and party1_type == payee_type:
                        return party2, party1  # Party2 pays Party1
        
        # Pattern 1: "X shall pay Y" or "X agrees to pay Y" or "X will pay Y"
        # This is the most explicit pattern
        pay_to_patterns = [
            rf'{re.escape(party1_lower)}.*?(?:shall|will|agrees?\s+to)\s+pay.*?{re.escape(party2_lower)}',
            rf'{re.escape(party2_lower)}.*?(?:shall|will|agrees?\s+to)\s+pay.*?{re.escape(party1_lower)}',
        ]
        
        for pattern in pay_to_patterns:
            if re.search(pattern, text_lower, re.DOTALL):
                # Check which party comes first (is the payer)
                if party1_lower in pattern:
                    if re.search(rf'{re.escape(party1_lower)}.*?(?:shall|will|agrees?\s+to)\s+pay.*?{re.escape(party2_lower)}', text_lower, re.DOTALL):
                        return party1, party2
                if party2_lower in pattern:
                    if re.search(rf'{re.escape(party2_lower)}.*?(?:shall|will|agrees?\s+to)\s+pay.*?{re.escape(party1_lower)}', text_lower, re.DOTALL):
                        return party2, party1
        
        # Pattern 2: "payment shall be made to Y" - Y is the payee
        payment_to_pattern = r'payment.*?(?:shall be )?made.*?to.*?(?:the\s+)?(\w+(?:\s+\w+)*?)'
        matches = re.finditer(payment_to_pattern, text_lower)
        for match in matches:
            payee_text = match.group(1)
            if party1_lower in payee_text or payee_text in party1_lower:
                return party2, party1
            elif party2_lower in payee_text or payee_text in party2_lower:
                return party1, party2
        
        # Pattern 3: "X shall be responsible for the payment" - X is the payer
        responsible_pattern = r'(\w+(?:\s+\w+)*?)\s+shall be responsible for.*?payment'
        matches = re.finditer(responsible_pattern, text_lower)
        for match in matches:
            payer_text = match.group(1)
            if party1_lower in payer_text or payer_text in party1_lower:
                return party1, party2
            elif party2_lower in payer_text or payer_text in party2_lower:
                return party2, party1
        
        # Pattern 4: Look for "The X" or "The Y" patterns near payment mentions
        # Often the document will say "The City shall pay the County" using articles
        the_party1 = f'the {party1_lower}'
        the_party2 = f'the {party2_lower}'
        
        if the_party1 in text_lower and the_party2 in text_lower:
            # Find positions of payment mentions with articles
            pay_pattern = rf'(?:the\s+)?(\w+(?:\s+\w+)*?)\s+(?:shall|will|agrees?\s+to)\s+pay\s+(?:to\s+)?(?:the\s+)?(\w+(?:\s+\w+)*?)'
            matches = re.finditer(pay_pattern, text_lower)
            for match in matches:
                payer = match.group(1).strip()
                payee = match.group(2).strip()
                
                if party1_lower in payer or payer in party1_lower:
                    if party2_lower in payee or payee in party2_lower:
                        return party1, party2
                if party2_lower in payer or payer in party2_lower:
                    if party1_lower in payee or payee in party1_lower:
                        return party2, party1
        
        # If still no match, count payment context mentions
        # The party mentioned more often in payment context is likely the payer
        party1_pay_count = len(re.findall(rf'{re.escape(party1_lower)}.{{0,100}}pay', text_lower))
        party2_pay_count = len(re.findall(rf'{re.escape(party2_lower)}.{{0,100}}pay', text_lower))
        
        if party1_pay_count > party2_pay_count:
            return party1, party2
        elif party2_pay_count > party1_pay_count:
            return party2, party1
        
        # Default: keep original order (Party 1 as principal, Party 2 as agent)
        # This is often the case in 28E agreements
        return party1, party2

    def extract_amount(self, text: str) -> float:
        """
        Extract the main contract amount from text
        Prioritizes total contract value over hourly/per-capita rates
        """
        amounts = []
        
        # First, try to find explicit total amounts
        for pattern in self.amount_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                amount_str = match.group('amount')
                amount = self.clean_amount(amount_str)
                if amount > 0:
                    # Get context to determine if this is the main amount
                    start = max(0, match.start() - 100)
                    end = min(len(text), match.end() + 100)
                    context = text[start:end].lower()
                    
                    # Prioritize amounts with "total", "annual", "sum"
                    priority = 0
                    if 'total' in context:
                        priority += 3
                    if 'annual' in context or 'yearly' in context:
                        priority += 2
                    if 'sum' in context:
                        priority += 2
                    if 'contract' in context:
                        priority += 1
                    
                    # Downgrade if it looks like a per-unit rate
                    if 'per capita' in context or 'per hour' in context or 'per month' in context:
                        priority -= 2
                    
                    amounts.append((amount, priority))
        
        # Try to calculate from rates with better context awareness
        # Per capita: look for population nearby
        per_capita_pattern = r'\$\s*(?P<rate>[\d,]+\.?\d*)\s+per\s+[Cc]apita'
        matches = re.finditer(per_capita_pattern, text)
        for match in matches:
            rate_str = match.group('rate')
            rate = self.clean_amount(rate_str)
            
            # Look for population/census numbers within 500 characters
            start = max(0, match.start() - 500)
            end = min(len(text), match.end() + 500)
            context = text[start:end]
            
            # Look for census/population numbers
            pop_patterns = [
                r'(?:census|population)[:\s]+(?P<pop>[\d,]+)',
                r'(?P<pop>[\d,]+)\s+(?:census|population)',
            ]
            
            for pop_pattern in pop_patterns:
                pop_match = re.search(pop_pattern, context, re.IGNORECASE)
                if pop_match:
                    pop_str = pop_match.group('pop')
                    pop = self.clean_amount(pop_str)
                    if 50 < pop < 100000:  # Reasonable population range
                        total = rate * pop
                        amounts.append((total, 2))
                        break
        
        # Per month: annualize it
        per_month_pattern = r'\$\s*(?P<rate>[\d,]+\.?\d*)\s+per\s+[Mm]onth'
        matches = re.finditer(per_month_pattern, text)
        for match in matches:
            rate_str = match.group('rate')
            rate = self.clean_amount(rate_str)
            total = rate * 12
            amounts.append((total, 1))
        
        # Per hour with total hours
        per_hour_pattern = r'\$\s*(?P<rate>[\d,]+\.?\d*)\s+per\s+[Hh]our'
        matches = re.finditer(per_hour_pattern, text)
        for match in matches:
            rate_str = match.group('rate')
            rate = self.clean_amount(rate_str)
            
            # Look for hour totals nearby
            start = max(0, match.start() - 200)
            end = min(len(text), match.end() + 200)
            context = text[start:end]
            
            hours_match = re.search(r'(?P<hours>[\d,]+)\s+hours?', context, re.IGNORECASE)
            if hours_match:
                hours_str = hours_match.group('hours')
                hours = self.clean_amount(hours_str)
                if hours > 0 and hours < 10000:  # Reasonable hour range
                    total = rate * hours
                    amounts.append((total, 1))
        
        # Return the amount with highest priority, or largest amount if tied
        if amounts:
            amounts.sort(key=lambda x: (x[1], x[0]), reverse=True)
            return amounts[0][0]
        
        return 0.0

    def parse_contract(self, text: str, pdf_id: str) -> Dict[str, any]:
        """
        Parse a single contract and extract principal, agent, and amount
        """
        if not text or pd.isna(text):
            return {
                'PDF_ID': pdf_id,
                'principal': '',
                'agent': '',
                'amount': 0.0
            }
        
        # Preprocess text to fix OCR errors
        text = self.preprocess_text(text)
        
        # Extract parties
        party1, party2 = self.extract_entities(text)
        
        # Determine payment relationship
        if party1 and party2:
            principal, agent = self.extract_payment_relationship(text, party1, party2)
        else:
            principal = party1 if party1 else ''
            agent = party2 if party2 else ''
        
        # Extract amount
        amount = self.extract_amount(text)
        
        # Clean up entity names - remove any remaining newlines and pollution
        if principal:
            principal = principal.replace('\n', ' ').replace('\r', ' ')
            principal = re.sub(r'\s+', ' ', principal).strip()
            principal = self.clean_entity_name(principal)
        if agent:
            agent = agent.replace('\n', ' ').replace('\r', ' ')
            agent = re.sub(r'\s+', ' ', agent).strip()
            agent = self.clean_entity_name(agent)
        
        return {
            'PDF_ID': pdf_id,
            'principal': principal if principal else '',
            'agent': agent if agent else '',
            'amount': amount
        }


def main():
    """Main function to process the contracts CSV file"""
    
    print("Loading contracts data...")
    df = pd.read_csv('ocr_contracts.csv')
    df = df.head(2).copy()
    
    print(f"Processing {len(df)} contracts...")
    
    parser = ContractParser()
    results = []
    
    # Process each contract
    for idx, row in df.iterrows():
        # if idx % 1000 == 0:
        #     print(f"  Processed {idx}/{len(df)} contracts...")
        
        pdf_id = row['PDF_ID']
        text = row['surya_ocr']
        
        result = parser.parse_contract(text, pdf_id)
        results.append(result)
    
    # Create output dataframe
    output_df = pd.DataFrame(results)
    
    # Drop the surya_ocr column - user can join it later using PDF_ID
    output_df = output_df[['PDF_ID', 'principal', 'agent', 'amount']]
    
    # Save to CSV
    output_path = 'extracted_contracts.csv'
    output_df.to_csv(output_path, index=False)
    
    print(f"\nExtraction complete!")
    print(f"Output saved to: {output_path}")
    print(f"\nSummary statistics:")
    print(f"  Total contracts: {len(output_df)}")
    print(f"  Contracts with principal identified: {(output_df['principal'] != '').sum()}")
    print(f"  Contracts with agent identified: {(output_df['agent'] != '').sum()}")
    print(f"  Contracts with amount > 0: {(output_df['amount'] > 0).sum()}")
    print(f"  Total contract value: ${output_df['amount'].sum():,.2f}")
    print(f"\nSample results:")
    print(output_df[['PDF_ID', 'principal', 'agent', 'amount']].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
