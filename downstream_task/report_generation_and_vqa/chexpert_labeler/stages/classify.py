"""Define mention classifier class."""
import logging
from pathlib import Path
from chexpert_labeler.negbio.negbio.pipeline import parse, ptb2ud, negdetect
from chexpert_labeler.negbio.negbio.neg import semgraph, propagator, neg_detector
from chexpert_labeler.negbio.negbio import ngrex
from tqdm import tqdm

from chexpert_labeler.constants import *


class ModifiedDetector(neg_detector.Detector):
    """Child class of NegBio Detector class.

    Overrides parent methods __init__, detect, and match_uncertainty.
    """
    def __init__(self, pre_negation_uncertainty_path,
                 negation_path, post_negation_uncertainty_path):
        self.neg_patterns = ngrex.load(negation_path)
        self.uncertain_patterns = ngrex.load(post_negation_uncertainty_path)
        self.preneg_uncertain_patterns\
            = ngrex.load(pre_negation_uncertainty_path)

    def detect(self, sentence, locs):
        """Detect rules in report sentences.

        Args:
            sentence(BioCSentence): a sentence with universal dependencies
            locs(list): a list of (begin, end)

        Return:
            (str, MatcherObj, (begin, end)): negation or uncertainty,
            matcher, matched annotation
        """
        logger = logging.getLogger(__name__)

        try:
            g = semgraph.load(sentence)
            propagator.propagate(g)
        except Exception:
            logger.exception('Cannot parse dependency graph ' +
                             f'[offset={sentence.offset}]')
            raise
        else:
            for loc in locs:
                for node in neg_detector.find_nodes(g, loc[0], loc[1]):
                    # Match pre-negation uncertainty rules first.
                    preneg_m = self.match_prenegation_uncertainty(g, node)
                    if preneg_m:
                        yield UNCERTAINTY, preneg_m, loc
                    else:
                        # Then match negation rules.
                        neg_m = self.match_neg(g, node)
                        if neg_m:
                            yield NEGATION, neg_m, loc
                        else:
                            # Finally match post-negation uncertainty rules.
                            postneg_m = self.match_uncertainty(g, node)
                            if postneg_m:
                                yield UNCERTAINTY, postneg_m, loc

    def match_uncertainty(self, graph, node):
        for pattern in self.uncertain_patterns:
            for m in pattern.finditer(graph):
                n0 = m.group(0)
                if n0 == node:
                    return m

    def match_prenegation_uncertainty(self, graph, node):
        for pattern in self.preneg_uncertain_patterns:
            for m in pattern.finditer(graph):
                n0 = m.group(0)
                if n0 == node:
                    return m


class Classifier(object):
    """Classify mentions of observations from radiology reports."""
    def __init__(self, pre_negation_uncertainty_path, negation_path,
                 post_negation_uncertainty_path, verbose=False):
        self.parser = parse.NegBioParser(model_dir=PARSING_MODEL_DIR)
        lemmatizer = ptb2ud.Lemmatizer()
        self.ptb2dep = ptb2ud.NegBioPtb2DepConverter(lemmatizer, universal=True)

        self.verbose = verbose

        self.detector = ModifiedDetector(pre_negation_uncertainty_path,
                                         negation_path,
                                         post_negation_uncertainty_path)

    def classify(self, collection):
        """Classify each mention into one of
        negative, uncertain, or positive."""
        documents = collection.documents
        if self.verbose:
            print("Classifying mentions...")
            documents = tqdm(documents)
        for document in documents:
            # Parse the impression text in place.
            self.parser.parse_doc(document)
            # Add the universal dependency graph in place.
            self.ptb2dep.convert_doc(document)
            # Detect the negation and uncertainty rules in place.
            negdetect.detect(document, self.detector)
            # To reduce memory consumption, remove sentences text.
            del document.passages[0].sentences[:]
