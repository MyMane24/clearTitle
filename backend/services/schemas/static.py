"""Per-document JSON schemas keyed by document type (extraction-only)."""
# â”€â”€ Schema definitions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


SALE_DEED_SCHEMA = {
    "document_type": "SALE_DEED",
    "file_metadata": {
        "registration_number": None,
        "execution_date": None,
        "registration_date": None,
        "issuing_office": None,
        "scanned_sheet_count": None,
    },
    "financial_summary": {
        "declared_consideration_amount": None,
        "stamp_duty_paid_amount": None,
        "total_registration_fees": None,
        "payment_dd_reference": None,
        "payment_breakdown": [
            {"amount": None, "mode": None, "instrument_reference": None, "instrument_date": None, "bank_branch": None}
        ],
    },
    "parties": {
        "vendors": [{"entity_name": None, "represented_by": None, "address": None}],
        "purchasers": [{"entity_name": None, "represented_by": None, "address": None}],
    },
    "property_schedule": {
        "cts_number": None,
        "survey_number": None,
        "apartment_or_shop_number": None,
        "floor_location": None,
        "project_name": None,
        "full_schedule_description": None,
        "measurements": {
            "dimensions_text": None,
            "super_built_up_area_sqft": None,
            "undivided_share_land_sqft": None,
            "total_land_area_sqmtr": None,
        },
        "boundaries": {"north": None, "east": None, "west": None, "south": None},
        "intended_usage": None,
    },
    "statutory_valuation_endorsement": {
        "estimated_market_value": None,
        "prevention_of_undervaluation_referred": False,
        "form_1a_communication_date": None,
    },
}

EC_SCHEMA = {
    "document_type": "ENCUMBRANCE_CERTIFICATE",
    "file_metadata": {
        "application_number": None,
        "certificate_number": None,
        "reference_number": None,
        "search_start_date": None,
        "search_end_date": None,
        "search_period_years": None,
        "digital_signature_by": None,
        "issuing_office": None,
    },
    "search_criteria": {
        "target_village": None,
        "target_hobli": None,
        "target_district": None,
        "target_identifiers": {
            "cts_number": None,
            "survey_number": None,
            "converted_survey_number": None,
            "plot_number": None,
        },
    },
    "historical_ledger": [
        {
            "transaction_index": 1,
            "execution_date": None,
            "registration_reference": None,
            "transaction_type": None,
            "parent_survey_number_raw": None,
            "locality_raw": None,
            "share_fraction": None,
            "is_agreement_to_sell": False,
            "minor_or_legal_heir_party": False,
            "financials": {"consideration_amount": None, "market_value": None},
            "parties": {"vendors": [], "purchasers": []},
            "property_details": {
                "plot_no": None, "pid_no": None, "cts_no": None,
                "description": None, "measurements": {},
                "boundaries": {"north": None, "east": None, "west": None, "south": None},
                "location": None,
            },
        }
    ],
}

PROPERTY_REGISTER_CARD_SCHEMA = {
    "document_type": "PROPERTY_REGISTER_CARD",
    "document_metadata": {
        "issuing_authority": None, "taluka": None, "district": None,
        "application_number": None, "application_date": None,
        "copy_ready_on": None, "copy_delivered_on": None,
        "copy_applied_by": None,
    },
    "property_identification": {
        "division_number_or_local_area_number": None, "local_area_name": None,
        "pt_sheet_number": None, "city_survey_number": None,
        "area_sq_meters": None, "tenure": None,
    },
    "holders": [{"name": None, "share": None, "notes": None}],
    "easements": None,
    "lessee": None,
    "other_encumbrances": None,
    "guidance_value": {"value": None, "order_number": None, "order_date": None},
    "property_boundaries_sketch_present": None,
    "mutation_or_transaction_entries": [
        {"date": None, "transaction": None, "volume_number": None,
         "new_holder_or_lessee_or_encumbrance": None, "attestation": None}
    ],
    "fees": {
        "copying_fee": None, "comparing_fee": None, "form_fee": None,
        "copying_surcharge": None, "round_off": None, "total": None,
    },
    "certification": {"signed_by": None, "designation": None, "office": None},
}

E_PAYMENT_RECEIPT_SCHEMA = {
    "document_type": "E_PAYMENT_RECEIPT",
    "document_metadata": {
        "issuing_authority": None, "city_or_local_body": None,
        "receipt_title": None, "source_website": None,
    },
    "consumer_details": {"owner_name": None, "pid": None, "ward_name": None},
    "transaction_details": {
        "transaction_number": None, "payment_reference_number": None,
        "status": None, "receipt_date": None,
    },
    "service_details": {"service_type": None, "assessment_year": None, "sas_number": None},
    "payment_details": {
        "service_charges": None, "amount_paid": None,
        "total_amount": None, "currency": "INR",
    },
    "notes": {"terms_and_conditions": [], "thank_you_message": None},
}

PROPERTY_TAX_ASSESSMENT_SCHEMA = {
    "document_type": "PROPERTY_TAX_ASSESSMENT",
    "document_metadata": {
        "issuing_authority": None, "form_number": None, "pid": None,
        "old_assessment_number": None, "new_assessment_number": None,
        "date": None, "document_datetime_raw": None,
        "assessment_year": None, "property_type": None,
    },
    "property_owner": {
        "owner_name": None, "occupier_name": None, "pid": None,
        "old_assessment_number": None, "new_assessment_number": None,
        "ward_number": None,
    },
    "assessment_rows": [
        {"row_number": None, "label": None, "value": None}
    ],
    "challan_copies": [
        {
            "copy_type": None,
            "pid": None,
            "challan_number": None,
            "receipt_number": None,
            "transaction_id": None,
            "bank_name": None,
            "bank_branch": None,
            "ward_number": None,
            "assessment_year": None,
            "owner_name": None,
            "property_address": None,
            "property_tax_amount": None,
            "penalty_amount": None,
            "service_charge": None,
            "rebate_amount": None,
            "total_amount_due": None,
            "amount_paid": None,
            "payment_date": None,
            "payment_mode": None,
            "payment_status": None,
            "remarks": None,
        }
    ],
    "validity": {"valid_for_month": None, "issued_by": None},
}


GIFT_DEED_SCHEMA = {
    "document_type": "GIFT_DEED",
    "file_metadata": {
        "registration_number": None, "document_number": None,
        "book_number": None, "cd_number": None,
        "execution_date": None, "registration_date": None,
        "registration_time": None, "registration_district": None,
        "issuing_office": None, "scanned_sheet_count": None,
        "drafted_by": None, "stamp_paper_society": None,
        "stamp_paper_price": None,
    },
    "financial_summary": {
        "stamp_duty_amount": None, "stamp_duty_payment_mode": None,
        "stamp_duty_certificate_reference": None,
        "stamp_duty_certificate_date": None, "registration_fee": None,
        "scanning_fee": None, "scrutiny_fee": None,
        "total_registration_fees": None,
    },
    "parties": {
        "donors": [{"entity_name": None, "age": None, "occupation": None,
                      "address": None, "aadhar_number": None}],
        "donees": [{"entity_name": None, "age": None, "occupation": None,
                      "address": None, "aadhar_number": None}],
        "relationship_between_parties": None,
        "reason_for_gift": None,
    },
    "property_schedule": {
        "plot_number": None, "survey_number": None, "cts_number": None,
        "full_schedule_description": None,
        "measurements": {
            "dimensions": None, "total_land_area_sqft": None,
            "total_land_area_gunthas": None,
            "ground_floor_building_area_sqmtrs": None,
            "first_floor_building_area_sqmtrs": None,
        },
        "boundaries": {"north": None, "east": None, "west": None, "south": None},
        "property_address": None, "property_type": None,
        "building_description": None,
    },
    "covenants": [],
    "registration_participants": {
        "presented_by": None, "executant": None, "claimant": None,
        "registering_officer_name": None,
        "registering_officer_designation": None,
    },
    "witnesses": [{"name": None, "address": None}],
    "certification": {
        "true_copy": None, "certifying_authority_name": None,
        "certifying_authority_qualification": None,
        "certifying_authority_location": None, "certification_date": None,
    },
}


PARTITION_DEED_SCHEMA = {
    "document_type": "PARTITION_DEED",
    "file_metadata": {
        "registration_number": None,
        "document_number": None,
        "book_number": None,
        "cd_number": None,
        "execution_date": None,
        "registration_date": None,
        "registration_time": None,
        "issuing_office": None,
        "scanned_sheet_count": None,
        "drafted_by": None,
    },
    "financial_summary": {
        "stamp_duty_paid_amount": None,
        "stamp_duty_payment_mode": None,
        "stamp_duty_certificate_reference": None,
        "stamp_duty_certificate_date": None,
        "registration_fee": None,
        "scanning_fee": None,
        "conversion_fee": None,
        "scrutiny_fee": None,
        "total_other_fees": None,
        "payment_breakdown": [
            {"amount": None, "mode": None, "instrument_reference": None, "instrument_date": None, "bank_branch": None}
        ],
    },
    "parties": {
        "coparceners": [{"entity_name": None, "age": None, "occupation": None, "address": None, "party_number": None}],
    },
    "property_schedule_a": {
        "survey_number": None,
        "cts_number": None,
        "municipal_number": None,
        "full_schedule_description": None,
        "measurements": {
            "dimensions_text": None,
            "total_land_area_sqyds": None,
            "total_land_area_sqft": None,
        },
        "boundaries": {"north": None, "east": None, "west": None, "south": None},
        "property_address": None,
    },
    "allocated_schedules": [
        {
            "schedule_name": None,
            "allocated_to_party_name": None,
            "survey_number": None,
            "cts_number": None,
            "municipal_number": None,
            "full_schedule_description": None,
            "measurements": {
                "dimensions_text": None,
                "total_land_area_sqyds": None,
                "total_land_area_sqft": None,
                "built_up_area_sqft": None,
            },
            "boundaries": {"north": None, "east": None, "west": None, "south": None},
            "property_address": None,
        }
    ],
    "witnesses": [{"name": None, "address": None}],
}

RTC_PAHANI_SCHEMA = {
    "document_type": "RTC_PAHANI",
    "land_details": {
        "survey_number": None,          # Column 1
        "hissa_number": None,           # Column 2
        "village": None,
        "hobli": None,
        "taluk": None,
        "district": None,
        "extent_details": {             # Column 3
            "total_extent_acres_gunthas": None,
            "kharab_land_a_acres_gunthas": None,
            "kharab_land_b_acres_gunthas": None,
            "net_area_acres_gunthas": None,
        },
        "revenue_details": {            # Column 4
            "land_revenue": None,
            "jodi": None,
            "cess": None,
            "water_rate": None,
            "total_revenue": None,
        },
        "soil_type": None,              # Column 5 (e.g. Masari)
        "tenure_type": None,            # Column 6 (e.g. Government/Freehold)
        "trees_count": [],              # Column 7 (e.g. Name + Count)
    },
    "owners_column_9": [                # Column 9 and 10
        {
            "owner_name": None,
            "father_husband_name": None,
            "extent_owned_acres_gunthas": None,
            "khata_number": None,
            "acquisition_mode_column_10": None, # e.g. "MR H551/2012-2013"
            "acquisition_date": None,
        }
    ],
    "other_rights_and_liabilities_column_11": { # Column 11
        "conditions_notes": None,               # à²·à²°à²¤à³à²¤à³à²—à²³à³ (e.g. NA conversion)
        "liabilities_loans": [],                 # à²‹à²£à²—à²³à³ (e.g. Bank mortgages)
    },
    "cultivator_crop_details_column_12": [      # Columns 12 to 16
        {
            "year": None,                       # e.g. 2023-2024
            "season": None,                     # e.g. Mungaru / Hingaru
            "cultivator_name": None,
            "cultivation_type": None,
            "cultivated_area_acres_gunthas": None,
            "crop_name": None,
            "crop_area": None,
        }
    ],
    "certification_metadata": {
        "signed_by": None,
        "signed_date": None,
        "rtc_unique_number": None,              # RTC UniqueNumber
        "bhoomi_land_id": None,                 # Bhoomi Land ID
    },
}

CONVERSION_ORDER_SCHEMA = {
    "document_type": "CONVERSION_ORDER",
    "file_metadata": {
        "order_number": None,                   # à²¸à²‚à²–à³à²¯à³† (e.g. 386986)
        "order_date": None,                     # à²¦à²¿à²¨à²¾à²‚à²•
        "issuing_office": None,                 # e.g. DC Office Dharwad
        "dc_name": None,                        # e.g. Gurudatta Narayana Hegde
        "applicant_name": None,                 # e.g. Chavan Ramesh
        "affidavit_number": None,
        "affidavit_date": None,
    },
    "financials": {
        "conversion_fee": None,                 # à²­à³‚ à²ªà²°à²¿à²µà²°à³à²¤à²¨à²¾ à²¶à³à²²à³à²•
        "podi_fee": None,                       # à²ªà³‹à²¡à²¿ à²¶à³à²²à³à²•
        "kharab_fee": None,
        "penalty_fee": None,                    # à²¦à²‚à²¡ à²¶à³à²²à³à²•
        "total_fee_paid": None,
        "payment_challans": [                   # Challan references
            {"challan_number": None, "challan_date": None, "amount": None}
        ],
    },
    "property_details": {
        "survey_number": None,
        "total_extent_acres_gunthas": None,
        "converted_extent_acres_gunthas": None,
        "converted_purpose": None,              # e.g. Apartment - Residential
        "boundaries": {                         # à²šà²•à³à²•à³à²¬à²‚à²¦à²¿
            "east": None,
            "west": None,
            "north": None,
            "south": None,
        },
    },
    "conditions": [],                           # Conditions 1-9 & Additional Conditions 1-4
}

MUTATION_SCHEMA = {
    "document_type": "MUTATION",
    "file_metadata": {
        "mutation_number": None,                # M.R. à²¨à²‚à²¬à²°à³
        "mutation_year": None,                  # à²µà²¹à²¿à²µà²¾à²Ÿà³ à²µà²°à³à²·
        "village": None,
        "hobli": None,
        "taluk": None,
        "district": None,
        "acquisition_mode": None,               # e.g. à²µà²¿à²­à²œà²¨à³† (Partition)
        "order_date": None,
    },
    "transaction_details": [                    # Division of survey numbers
        {
            "old_survey_number": None,
            "old_extent_acres_gunthas": None,
            "old_revenue": None,
            "new_survey_number": None,
            "new_extent_acres_gunthas": None,
            "new_revenue": None,
            "owner_name": None,
        }
    ],
    "attestation": {
        "attested_by": None,
        "attested_date": None,
        "status": None,
    },
}

CDP_PLAN_SCHEMA = {
    "document_type": "CDP_PLAN",
    "file_metadata": {
        "approval_number": None,
        "approval_date": None,
        "approving_authority": None,
        "survey_numbers_covered": [],
    },
    "zoning_classification": None,
    "road_width_meters": None,
}

RERA_CERTIFICATE_SCHEMA = {
    "document_type": "RERA_CERTIFICATE",
    "file_metadata": {
        "registration_number": None,
        "acknowledgement_number": None,
        "acknowledgement_date": None,
        "approval_date": None,
        "expiry_date": None,
        "issuing_authority": None,
    },
    "project_details": {
        "project_name": None,
        "promoter_name": None,
        "project_address": None,
        "survey_numbers": [],
        "cts_numbers": [],
        "plots_covered": [],
        "locality": None,
    },
    "promoter_details": {
        "registered_office_address": None,
    },
}

LITIGATION_AFFIDAVIT_SCHEMA = {
    "document_type": "LITIGATION_AFFIDAVIT",
    "file_metadata": {
        "stamp_certificate_number": None,
        "stamp_certificate_date": None,
        "stamp_duty_amount": None,
        "notary_name": None,
        "notary_exp_date": None,
        "notary_reg_number": None,
        "deponent_name": None,
    },
    "project_details": {
        "project_name": None,
        "promoter_name": None,
        "survey_number": None,
        "cts_number": None,
        "plot_number": None,
        "total_area_sq_meters": None,
    },
    "declaration_details": {
        "is_free_from_encumbrances": None,
        "no_claims_or_litigations": None,
    },
}

ALLOTMENT_LETTER_SCHEMA = {
    "document_type": "ALLOTMENT_LETTER",
    "file_metadata": {
        "letter_number": None,
        "letter_date": None,
        "rera_registration_number": None,
    },
    "allotment_details": {
        "project_name": None,
        "promoter_name": None,
        "allottee_name": None,
        "unit_number": None,
        "floor_number": None,
        "wing_or_block": None,
        "carpet_area_sq_mts": None,
        "carpet_area_sq_ft": None,
        "parking_allotted": None,
        "parking_details": None,
        "project_address": None,
        "survey_numbers": [],
        "cts_numbers": [],
        "plots_covered": [],
    },
    "financial_details": {
        "total_consideration_amount": None,
        "booking_amount_received": None,
        "booking_amount_pct": None,
        "booking_payment_date": None,
    },
    "possession_date": None,
}

BUILDING_LICENSE_SCHEMA = {
    "document_type": "BUILDING_LICENSE",
    "file_metadata": {
        "license_number": None,
        "license_date": None,
        "application_number": None,
        "application_date": None,
        "issuing_authority": None,
        "valid_from": None,
        "valid_to": None,
    },
    "property_details": {
        "owner_name": None,
        "survey_number": None,
        "cts_number": None,
        "site_number": None,
        "plot_area_sq_meters": None,
        "far_approved": None,
        "boundaries": {
            "east": None,
            "west": None,
            "north": None,
            "south": None,
        },
    },
    "building_specifications": {
        "floors": [
            {"floor_name": None, "use": None, "area_sq_meters": None}
        ],
        "total_built_up_area_sq_meters": None,
    },
    "financial_details": {
        "total_fee_paid": None,
        "receipt_number": None,
        "receipt_date": None,
    },
}

COMPLETION_CERTIFICATE_SCHEMA = {
    "document_type": "COMPLETION_CERTIFICATE",
    "file_metadata": {
        "certificate_number": None,
        "certificate_date": None,
        "issuing_office": None,
        "scanned_sheet_count": None,
    },
    "application_details": {
        "applicant_name": None,
        "application_date": None,
        "building_permission_letter_reference": None,
        "building_permission_letter_date": None,
    },
    "inspection_details": {
        "inspected_by": None,
        "inspection_date": None,
    },
    "property_details": {
        "survey_number": None,
        "cts_number": None,
        "location": None,
        "supervising_architect_engineer": None,
        "fit_for_occupation_floors": [],
        "intended_use": None,
    },
}

SCHEMA_MAP = {
    "SALE_DEED": SALE_DEED_SCHEMA,
    "ENCUMBRANCE_CERTIFICATE": EC_SCHEMA,
    "PROPERTY_REGISTER_CARD": PROPERTY_REGISTER_CARD_SCHEMA,
    "E_PAYMENT_RECEIPT": E_PAYMENT_RECEIPT_SCHEMA,
    "PROPERTY_TAX_ASSESSMENT": PROPERTY_TAX_ASSESSMENT_SCHEMA,
    "TAX_RECEIPT": E_PAYMENT_RECEIPT_SCHEMA,
    "GIFT_DEED": GIFT_DEED_SCHEMA,
    "RTC_PAHANI": RTC_PAHANI_SCHEMA,
    "CONVERSION_ORDER": CONVERSION_ORDER_SCHEMA,
    "MUTATION": MUTATION_SCHEMA,
    "CDP_PLAN": CDP_PLAN_SCHEMA,
    "RERA_CERTIFICATE": RERA_CERTIFICATE_SCHEMA,
    "LITIGATION_AFFIDAVIT": LITIGATION_AFFIDAVIT_SCHEMA,
    "ALLOTMENT_LETTER": ALLOTMENT_LETTER_SCHEMA,
    "BUILDING_LICENSE": BUILDING_LICENSE_SCHEMA,
    "PARTITION_DEED": PARTITION_DEED_SCHEMA,
    "COMPLETION_CERTIFICATE": COMPLETION_CERTIFICATE_SCHEMA,
}
