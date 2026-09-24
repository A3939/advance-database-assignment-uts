# C11 — VIC Source Model and Query Evidence

> Internal development / evidence note  
> Role: C  
> Status: Draft v0.1

## 1. Purpose

C11 documents the four-resource VIC source model and provides
query evidence for real relationship, duplicate, conflict and
JOIN-multiplication risks.

The four resources are:

- Accident
- Vehicle
- Person
- Node

The objective is to preserve their native grains and relationships
rather than flattening them into one multiplied result set.

## 2. VIC four-resource relationship model

### 2.1 Accident

Native crash identity:

`ACCIDENT_NO`

Accident is the parent crash resource.

### 2.2 Vehicle

Native Vehicle identity:

`ACCIDENT_NO + VEHICLE_ID`

Relationship to Accident:

`Vehicle.ACCIDENT_NO -> Accident.ACCIDENT_NO`

One Accident may have multiple Vehicle rows.

### 2.3 Person

Candidate Person identity:

`ACCIDENT_NO + PERSON_ID`

Relationship to Accident:

`Person.ACCIDENT_NO -> Accident.ACCIDENT_NO`

Where `VEHICLE_ID` is non-empty, Person-to-Vehicle matching must use:

`ACCIDENT_NO + VEHICLE_ID`

`VEHICLE_ID` must not be matched independently of its Accident.

### 2.4 Node

Crash-specific Node grouping uses:

`ACCIDENT_NO + NODE_ID`

This is a grouping/matching key, not a unique physical-row key.

One Accident/Node group may contain multiple source observations.

Repeated Node observations remain in Raw and must not multiply
crash or location counts.

## 3. Relationship diagram

```text
                       Accident
                     ACCIDENT_NO
                    /     |      \
                   /      |       \
                  /       |        \
                 v        v         v

            Vehicle     Person      Node
        ACCIDENT_NO   ACCIDENT_NO   ACCIDENT_NO
        VEHICLE_ID    PERSON_ID     NODE_ID
             ^            |
             |            |
             +------------+
              Person Vehicle reference
              ACCIDENT_NO + VEHICLE_ID
